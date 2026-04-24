import asyncio
import sys
import os

# On ajoute le chemin du backend pour que Python trouve le module 'app'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import async_engine
from app.services.userService import UserService
from sqlalchemy.orm import sessionmaker


async def create_main_user():
    print("🚀 Initialisation du compte de test Sharaco...")

    async_session = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as db:
        email = "bramslevel129@gmail.com"
        password = "password123"

        # 1. Vérifier si l'utilisateur existe déjà pour éviter les doublons
        existing_user = await UserService.get_by_email(db, email)

        if existing_user:
            print(f"⚠️ L'utilisateur {email} existe déjà en base de données.")
        else:
            # 2. Création via le service (qui gère le hashage du mot de passe)
            try:
                new_user = await UserService.create_user(db, email, password)
                print(f"✅ Utilisateur créé avec succès : {new_user.email}")
                print(f"🆔 ID généré : {new_user.id}")
                print("---")
                print("Tu peux maintenant te connecter avec :")
                print(f"Email : {email}")
                print(f"Password : {password}")
            except Exception as e:
                print(f"❌ Erreur lors de la création : {e}")


if __name__ == "__main__":
    asyncio.run(create_main_user())