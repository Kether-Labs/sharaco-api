# app/services/pdfRenderer.py
import os
import hashlib
import json
import asyncio
from pathlib import Path
from collections import OrderedDict
from io import BytesIO
from jinja2 import Environment, FileSystemLoader
from PIL import Image
from playwright.async_api import async_playwright
from sqlmodel import select
from app.core.currency import get_currency_symbol
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document, DocumentItem
from app.models.document_template import DocumentTemplate
from app.models.client import Client
from app.models.user import User
import logging
from datetime import datetime, timezone
from uuid import uuid4
from app.models.document import DocumentType, DocumentStatus
from app.models.payment_schedule import PaymentSchedule, MilestoneStatus

logger = logging.getLogger(__name__)


class PDFRenderer:
    """Moteur de rendu HTML/PDF/PNG haute performance pour les devis et factures."""

    TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
    CACHE_DIR = Path(__file__).parent.parent.parent / "storage" / "cache" / "previews"
    MAX_MEMORY_CACHE = 256

    QUOTE_LAYOUT_MAP = {
        "classic": "classic.html",
        "modern": "modern.html",
        "minimal": "minimal.html",
        "bold": "bold.html",
        "elegant": "elegant.html",
        "premium": "premium.html",
        "bento": "bento.html",
        "studio": "studio.html",
    }

    INVOICE_TEMPLATE = "facture.html"
    DEFAULT_CURRENCY = "FCFA"

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATES_DIR)),
            autoescape=True,
            cache_size=100,
        )
        self._preview_cache: dict[str, bytes] = {}
        self._memory_cache: OrderedDict[str, bytes] = OrderedDict()
        self._document_preview_cache = self._memory_cache  # Rétrocompatibilité

        # Playwright persistent instance
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()
        self._render_semaphore = asyncio.Semaphore(4)
        self._inflight_renders: dict[str, asyncio.Future] = {}

    async def _ensure_browser(self):
        """Initialise ou retourne l'instance Chromium persistante."""
        if self._browser is not None and self._browser.is_connected():
            return self._browser

        async with self._browser_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--no-first-run",
                ],
            )
            logger.info("🚀 Chromium persistant prêt pour PDFRenderer")
            return self._browser

    async def warmup(self):
        """Préchauffe le navigateur Playwright au démarrage de l'application."""
        try:
            await self._ensure_browser()
            logger.info("⚡ Navigateur Chromium préchauffé avec succès")
        except Exception as e:
            logger.warning(f"⚠️ Échec du préchauffage Chromium: {e}")

    async def close(self):
        """Ferme proprement Chromium et Playwright lors du shutdown."""
        async with self._browser_lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            logger.info("🛑 Chromium PDFRenderer fermé")

    def _get_layout_file(self, layout_style: str, doc_type: DocumentType) -> str:
        if doc_type == DocumentType.FACTURE:
            return self.INVOICE_TEMPLATE
        return self.QUOTE_LAYOUT_MAP.get(layout_style, "classic.html")

    @staticmethod
    def _calculate_totals(items: list[DocumentItem]) -> dict:
        subtotal_cents = 0
        tax_total_cents = 0

        for item in items:
            line_subtotal = item.quantity * item.unit_price_cents
            line_tax = int(line_subtotal * item.tax_rate / 100)
            subtotal_cents += line_subtotal
            tax_total_cents += line_tax

        grand_total_cents = subtotal_cents + tax_total_cents

        return {
            "subtotal_cents": subtotal_cents,
            "tax_total_cents": tax_total_cents,
            "grand_total_cents": grand_total_cents,
        }

    # ═══════════════════════════════════════════════════════════
    # CACHE DISQUE & MÉMOIRE
    # ═══════════════════════════════════════════════════════════

    MAX_DISK_CACHE_FILES = 500

    def _read_from_disk_cache(self, cache_key: str) -> bytes | None:
        try:
            path = self.CACHE_DIR / f"{cache_key}.png"
            if path.exists():
                # Met à jour l'heure d'accès pour la politique LRU
                os.utime(path, None)
                return path.read_bytes()
        except Exception as e:
            logger.warning(f"⚠️ Erreur lecture cache disque ({cache_key}): {e}")
        return None

    def _cleanup_old_document_versions(self, document_id, current_hash: str):
        """Supprime les anciennes versions du document sur disque et mémoire vive."""
        prefix = f"{document_id}_"
        # Nettoyage mémoire
        for k in list(self._memory_cache.keys()):
            if k.startswith(prefix) and current_hash not in k:
                self._memory_cache.pop(k, None)

        # Nettoyage disque
        try:
            if self.CACHE_DIR.exists():
                for f in self.CACHE_DIR.glob(f"{document_id}_*.png"):
                    if current_hash not in f.name:
                        try:
                            f.unlink()
                        except OSError:
                            pass
        except Exception as e:
            logger.warning(f"⚠️ Erreur nettoyage anciens previews ({document_id}): {e}")

    def _evict_disk_cache_if_needed(self):
        """Empêche le dossier storage de se remplir : éviction LRU des fichiers les plus anciens."""
        try:
            if not self.CACHE_DIR.exists():
                return
            files = list(self.CACHE_DIR.glob("*.png"))
            if len(files) > self.MAX_DISK_CACHE_FILES:
                # Trie du plus ancien au plus récent
                files.sort(key=lambda f: f.stat().st_mtime)
                to_delete = files[:len(files) - self.MAX_DISK_CACHE_FILES]
                for f in to_delete:
                    try:
                        f.unlink()
                    except OSError:
                        pass
                logger.info(f"🧹 Cache disque régulé: {len(to_delete)} anciens fichiers supprimés (quota {self.MAX_DISK_CACHE_FILES})")
        except Exception as e:
            logger.warning(f"⚠️ Erreur éviction cache disque: {e}")

    def _write_to_disk_cache(self, cache_key: str, data: bytes):
        try:
            self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self.CACHE_DIR / f"{cache_key}.png"
            tmp_path = self.CACHE_DIR / f"{cache_key}.tmp.{uuid4().hex[:8]}"
            tmp_path.write_bytes(data)
            tmp_path.replace(path)
            self._evict_disk_cache_if_needed()
        except Exception as e:
            logger.warning(f"⚠️ Erreur écriture cache disque ({cache_key}): {e}")

    def invalidate_document_cache(self, document_id):
        """Supprime manuellement toutes les images en cache d'un document."""
        prefix = f"{document_id}_"
        for k in list(self._memory_cache.keys()):
            if k.startswith(prefix):
                self._memory_cache.pop(k, None)
        try:
            if self.CACHE_DIR.exists():
                for f in self.CACHE_DIR.glob(f"{document_id}_*.png"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
        except Exception as e:
            logger.warning(f"⚠️ Erreur invalidation cache document ({document_id}): {e}")

    def _put_memory_cache(self, cache_key: str, data: bytes):
        self._memory_cache[cache_key] = data
        self._memory_cache.move_to_end(cache_key)
        if len(self._memory_cache) > self.MAX_MEMORY_CACHE:
            self._memory_cache.popitem(last=False)

    @staticmethod
    def _resize_png(png_bytes: bytes, target_width: int) -> bytes:
        """Redimensionne une image PNG avec Pillow de façon optimisée."""
        try:
            with Image.open(BytesIO(png_bytes)) as img:
                orig_w, orig_h = img.size
                if orig_w <= target_width:
                    return png_bytes
                target_height = int(orig_h * (target_width / orig_w))
                resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                out = BytesIO()
                resized.save(out, format="PNG", optimize=True)
                return out.getvalue()
        except Exception as e:
            logger.warning(f"⚠️ Erreur redimensionnement PNG ({target_width}px): {e}")
            return png_bytes

    # ═══════════════════════════════════════════════════════════
    # ✅ CACHE INTELLIGENT (hash du contenu)
    # ═══════════════════════════════════════════════════════════

    def compute_render_hash(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        items: list = None,
        schedule: list = None,
    ) -> str:
        """
        Calcule un hash MD5 de TOUT ce qui influence le rendu visuel.
        Si un seul élément change → hash différent → nouvelle image automatiquement.
        """
        def _status(v):
            return v.value if hasattr(v, "value") else str(v)

        doc_items = items if items is not None else (document.items or [])
        doc_schedule = schedule if schedule is not None else (document.payment_schedule or [])

        payload = {
            # Document
            "doc": {
                "number": document.number,
                "status": _status(document.status),
                "type": _status(document.type),
                "invoice_type": getattr(document, "invoice_type", None),
                "source_id": str(getattr(document, "source_document_id", None)),
                "layout": document.layout_style,
                "notes": document.notes,
                "due": document.due_date.isoformat() if document.due_date else None,
                "created": document.created_at.isoformat() if document.created_at else None,
                "colors": [
                    document.primary_color, document.secondary_color, document.accent_color,
                    document.background_color, document.text_color, document.font_family,
                ],
            },
            # Template
            "tpl": [
                getattr(template, "logo_url", None),
                getattr(template, "header_text", None),
                getattr(template, "footer_text", None),
                getattr(template, "show_bank_details", None),
                getattr(template, "show_tax_id", None),
                getattr(template, "primary_color", None),
            ],
            # User (infos entreprise affichées)
            "user": [
                user.company_name, user.address, getattr(user, "phone", None),
                user.email, user.tax_id, getattr(user, "vat_number", None),
                user.payment_info, getattr(user, "currency", None),
            ],
            # Client (affiché sur le document)
            "client": [client.name, client.email, getattr(client, "phone", None), client.address] if client else None,
            # Lignes du document
            "items": [
                [i.description, i.quantity, i.unit_price_cents, i.tax_rate]
                for i in (doc_items or [])
            ],
            # Échéancier (statuts + dates de paiement)
            "schedule": [
                [m.sequence, m.title, m.percent, m.amount_cents, _status(m.status),
                 m.paid_at.isoformat() if m.paid_at else None]
                for m in (doc_schedule or [])
            ],
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()

    def _compute_render_hash(self, *args, **kwargs) -> str:
        """Alias rétrocompatible pour compute_render_hash."""
        return self.compute_render_hash(*args, **kwargs)

    async def get_or_render_document_png(
        self,
        db: AsyncSession,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        content_hash: str = None,
        width: int | None = None,
    ) -> bytes:
        """
        Retourne le PNG d'un document avec cache hybride (Mémoire LRU + Disque)
        et déduplication des requêtes concurrentes (single-flight).
        """
        items = document.items or []
        schedule = document.payment_schedule or []

        if not content_hash:
            content_hash = self.compute_render_hash(document, template, user, client, items, schedule)

        base_cache_key = f"{document.id}_{content_hash}"
        cache_key = f"{base_cache_key}_w{width}" if width else base_cache_key

        # 1️⃣ Niveau 1 : Mémoire vive (0ms)
        if cache_key in self._memory_cache:
            logger.info(f"⚡ Preview {document.id} servie depuis le cache mémoire ({cache_key})")
            return self._memory_cache[cache_key]

        # 2️⃣ Niveau 2 : Disque persistant (~1ms)
        disk_bytes = self._read_from_disk_cache(cache_key)
        if disk_bytes is not None:
            logger.info(f"💾 Preview {document.id} servie depuis le cache disque ({cache_key})")
            self._put_memory_cache(cache_key, disk_bytes)
            return disk_bytes

        # Si un thumbnail est demandé et que l'original est déjà présent (en mémoire ou disque)
        if width:
            full_png = self._memory_cache.get(base_cache_key) or self._read_from_disk_cache(base_cache_key)
            if full_png is not None:
                resized_png = self._resize_png(full_png, width)
                self._put_memory_cache(cache_key, resized_png)
                self._write_to_disk_cache(cache_key, resized_png)
                return resized_png

        # 3️⃣ Single-flight : Attente si un rendu pour cette même clé est déjà en cours
        loop = asyncio.get_running_loop()
        if cache_key in self._inflight_renders:
            logger.info(f"⏳ Preview {document.id} en attente du rendu parallèle...")
            return await self._inflight_renders[cache_key]

        future = loop.create_future()
        self._inflight_renders[cache_key] = future

        try:
            logger.info(f"🔄 Preview {document.id} en cours de génération via Chromium...")
            html = await self.render_html(
                document=document,
                template=template,
                user=user,
                client=client,
                db=db,
            )
            raw_png = await self.render_png_from_html(html)

            # Mise en cache de l'original pleine taille
            self._put_memory_cache(base_cache_key, raw_png)
            self._write_to_disk_cache(base_cache_key, raw_png)
            # Supprime automatiquement les anciennes versions périmées de ce document
            self._cleanup_old_document_versions(document.id, content_hash)

            if width:
                final_png = self._resize_png(raw_png, width)
                self._put_memory_cache(cache_key, final_png)
                self._write_to_disk_cache(cache_key, final_png)
            else:
                final_png = raw_png

            if not future.done():
                future.set_result(final_png)
            return final_png

        except Exception as e:
            if not future.done():
                future.set_exception(e)
            raise
        finally:
            self._inflight_renders.pop(cache_key, None)

    # ═══════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════
    # CONTEXTE JINJA
    # ═══════════════════════════════════════════════════════════

    async def _build_invoice_schedule_context(self, db: AsyncSession, document: Document) -> dict:
        """
        Construit le contexte 'Suivi de paiement' pour une FACTURE :
        remonte au devis parent, lit son échéancier, calcule la progression
        et identifie la tranche correspondant à cette facture.
        """
        empty = {
            "payment_schedule": [],
            "current_milestone": None,
            "current_amount_cents": None,
            "paid_percent": 0,
            "paid_amount_cents": 0,
            "total_schedule_cents": 0,
            "source_quote_number": None,
            "has_schedule": False,
        }

        if document.type != DocumentType.FACTURE or not document.source_document_id:
            return empty

        quote = await db.get(Document, document.source_document_id)
        if not quote:
            return empty

        result = await db.execute(
            select(PaymentSchedule)
            .where(PaymentSchedule.document_id == quote.id)
            .order_by(PaymentSchedule.sequence.asc())
        )
        milestones = list(result.scalars().all())

        if not milestones or len(milestones) < 2:
            return empty

        rows = []
        for m in milestones:
            rows.append({
                "sequence": m.sequence,
                "title": m.title,
                "percent": m.percent,
                "amount_cents": m.amount_cents or 0,
                "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                "paid_at": m.paid_at,
                "is_current": m.invoice_id == document.id,
            })

        current = next((r for r in rows if r["is_current"]), None)
        total_cents = sum(r["amount_cents"] for r in rows)
        paid_cents = sum(r["amount_cents"] for r in rows if r["status"] == "PAID")
        paid_percent = int(round(paid_cents / total_cents * 100)) if total_cents else 0

        return {
            "payment_schedule": rows,
            "current_milestone": current,
            "current_amount_cents": current["amount_cents"] if current else None,
            "paid_percent": paid_percent,
            "paid_amount_cents": paid_cents,
            "total_schedule_cents": total_cents,
            "source_quote_number": quote.number,
            "has_schedule": True,
        }

    async def _get_source_quote_number(self, db: AsyncSession, document: Document) -> str | None:
        if document.type != DocumentType.FACTURE or not document.source_document_id:
            return None

        try:
            stmt = select(Document).where(Document.id == document.source_document_id)
            result = await db.execute(stmt)
            source = result.scalar_one_or_none()
            return source.number if source else None
        except Exception as e:
            logger.warning(f"Impossible de charger le devis source: {e}")
            return None

    def _build_context(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
        source_quote_number: str | None = None,
    ) -> dict:
        totals = self._calculate_totals(document.items)

        context = {
            "document": document,
            "template": template,
            "user": user,
            "client": client,
            "items": document.items,
            "totals": totals,
            "currency": get_currency_symbol(user.currency or "XOF"),
            "source_quote_number": source_quote_number,
        }
        return context

    async def render_html(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
        db: AsyncSession = None,
    ) -> str:
        """
        Rend le HTML d'un document (devis ou facture).
        Nécessite une session DB pour charger les relations (devis source, échéancier).
        """
        try:
            layout_file = self._get_layout_file(template.layout_style, document.type)
            tmpl = self.env.get_template(layout_file)

            source_quote_number = await self._get_source_quote_number(db, document)

            context = self._build_context(
                document, template, user, client, currency, source_quote_number
            )

            # ✅ Fusionner le suivi de paiement pour les factures
            if db:
                schedule_context = await self._build_invoice_schedule_context(db, document)
                context.update(schedule_context)

            return tmpl.render(**context)
        except Exception as e:
            logger.error(f"Erreur lors du rendu HTML: {e}", exc_info=True)
            raise

    def render_html_preview(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> str:
        """
        Rend le HTML pour le preview en temps réel (pas de DB).
        Le suivi de paiement sera masqué (has_schedule = False par défaut).
        """
        try:
            layout_file = self._get_layout_file(template.layout_style, document.type)
            tmpl = self.env.get_template(layout_file)
            context = self._build_context(document, template, user, client, currency)
            return tmpl.render(**context)
        except Exception as e:
            logger.error(f"Erreur lors du rendu HTML preview: {e}", exc_info=True)
            raise

    def _get_mock_user(self) -> User:
        return User(
            id=uuid4(),
            email="demo@exemple.com",
            company_name="Entreprise Démo SARL",
            address="123 Avenue de la République\n75001 Paris, France",
            phone="+33 1 23 45 67 89",
            tax_id="FR12345678901",
            vat_number="FR12345678901",
            payment_info="IBAN: FR76 1234 5678 9012 3456 7890 123\nBIC: BNPAFRPP\nBanque: BNP Paribas",
        )

    def render_preview_html(
        self,
        template: DocumentTemplate,
        user: User = None,
        currency: str = None,
        doc_type: DocumentType = DocumentType.DEVIS,
    ) -> str:
        if user is None:
            user = self._get_mock_user()

        fake_doc = Document(
            id=uuid4(),
            type=doc_type,
            status=DocumentStatus.DRAFT if doc_type == DocumentType.DEVIS else DocumentStatus.SENT,
            number="DEV-2026-001" if doc_type == DocumentType.DEVIS else "FACT-2026-001",
            created_at=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            user_id=user.id,
            client_id=uuid4(),
            template_id=None,
        )

        fake_client = Client(
            id=uuid4(),
            name="Client Exemple SARL",
            email="contact@client-exemple.com",
            address="456 Boulevard Saint-Germain\n75007 Paris, France",
            phone="+33 1 98 76 54 32",
            user_id=user.id,
        )

        fake_items = [
            DocumentItem(
                id=uuid4(),
                description="Développement site web vitrine",
                quantity=1,
                unit_price_cents=50000000,
                tax_rate=19.25,
                document_id=fake_doc.id,
            ),
            DocumentItem(
                id=uuid4(),
                description="Hébergement annuel (12 mois)",
                quantity=1,
                unit_price_cents=5000000,
                tax_rate=19.25,
                document_id=fake_doc.id,
            ),
            DocumentItem(
                id=uuid4(),
                description="Maintenance mensuelle (x3)",
                quantity=3,
                unit_price_cents=3000000,
                tax_rate=19.25,
                document_id=fake_doc.id,
            ),
        ]
        fake_doc.items = fake_items

        return self.render_html_preview(fake_doc, template, user, fake_client, currency)

    # ═══════════════════════════════════════════════════════════
    # PLAYWRIGHT : screenshots & PDF (Haute performance)
    # ═══════════════════════════════════════════════════════════

    async def _generate_screenshot(self, html_string: str) -> bytes:
        return await self.render_png_from_html(html_string)

    async def render_template_preview_png(
        self,
        layout_style: str,
        currency: str = "FCFA",
    ) -> bytes:
        if layout_style in self._preview_cache:
            logger.info(f"Preview template {layout_style} servi depuis le cache")
            return self._preview_cache[layout_style]

        try:
            mock_template = DocumentTemplate(
                id=uuid4(),
                name=f"Template {layout_style}",
                layout_style=layout_style,
                primary_color="#0ea5e9" if layout_style == "modern" else "#1a1a1a",
                secondary_color="#64748b",
                footer_text="Aperçu du template - Document généré automatiquement",
                show_tax_id=True,
                show_bank_details=True,
            )

            html_string = self.render_preview_html(
                template=mock_template,
                user=None,
                currency=currency,
                doc_type=DocumentType.DEVIS,
            )

            screenshot = await self.render_png_from_html(html_string)
            self._preview_cache[layout_style] = screenshot
            logger.info(f"Preview template {layout_style} généré et mis en cache")
            return screenshot

        except Exception as e:
            logger.error(f"Erreur génération preview template PNG: {e}", exc_info=True)
            raise

    async def render_png_from_html(self, html_string: str) -> bytes:
        """Génère un PNG depuis une chaîne HTML en réutilisant le navigateur Chromium."""
        async with self._render_semaphore:
            browser = await self._ensure_browser()
            context = await browser.new_context(
                viewport={"width": 794, "height": 1123},
                device_scale_factor=1,
            )
            page = await context.new_page()
            try:
                await page.set_content(html_string, wait_until="load")
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                screenshot = await page.screenshot(full_page=True, type="png")
                return screenshot
            except Exception as e:
                if "Target page, context or browser has been closed" in str(e) or not browser.is_connected():
                    self._browser = None
                logger.error(f"Erreur génération PNG depuis HTML: {e}", exc_info=True)
                raise
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass

    async def render_pdf_from_html(self, html_string: str) -> BytesIO:
        """Génère un PDF depuis une chaîne HTML via Chromium persistant."""
        async with self._render_semaphore:
            browser = await self._ensure_browser()
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.set_content(html_string, wait_until="load")
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "15mm", "right": "20mm", "bottom": "15mm", "left": "20mm"},
                )
                pdf_buffer = BytesIO(pdf_bytes)
                pdf_buffer.seek(0)
                return pdf_buffer
            except Exception as e:
                if "Target page, context or browser has been closed" in str(e) or not browser.is_connected():
                    self._browser = None
                logger.error(f"Erreur génération PDF depuis HTML: {e}", exc_info=True)
                raise
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass

    async def render_pdf(
        self,
        db: AsyncSession,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> BytesIO:
        """Génère le PDF d'un document complet via Chromium persistant."""
        try:
            html_string = await self.render_html(
                document=document,
                template=template,
                user=user,
                client=client,
                currency=currency,
                db=db,
            )

            async with self._render_semaphore:
                browser = await self._ensure_browser()
                context = await browser.new_context()
                page = await context.new_page()
                try:
                    await page.set_content(html_string, wait_until="load")
                    try:
                        await page.evaluate("document.fonts.ready")
                    except Exception:
                        pass
                    pdf_bytes = await page.pdf(
                        format="A4",
                        print_background=True,
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    )
                    pdf_buffer = BytesIO(pdf_bytes)
                    pdf_buffer.seek(0)
                    return pdf_buffer
                except Exception as e:
                    if "Target page, context or browser has been closed" in str(e) or not browser.is_connected():
                        self._browser = None
                    logger.error(f"Erreur génération PDF: {e}", exc_info=True)
                    raise
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass
                    try:
                        await context.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Erreur rendu PDF document: {e}", exc_info=True)
            raise


# Instance globale
pdf_renderer = PDFRenderer()