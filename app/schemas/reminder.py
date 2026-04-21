from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class ReminderConfigCreate(BaseModel):
    reminder_1_enabled: bool = True
    reminder_1_days: int = 1
    reminder_1_subject: str = "Rappel : Votre devis {number} est en attente"

    reminder_2_enabled: bool = True
    reminder_2_days: int = 3
    reminder_2_subject: str = "Suivi : Devis {number} - Avez-vous bien recu ?"

    reminder_3_enabled: bool = False
    reminder_3_days: int = 7
    reminder_3_subject: str = "Dernier rappel : Devis {number} expire bientot"

    is_active: bool = True
    stop_on_view: bool = True
    stop_on_payment: bool = True


class ReminderConfigRead(BaseModel):
    id: UUID
    user_id: UUID
    reminder_1_enabled: bool
    reminder_1_days: int
    reminder_1_subject: str
    reminder_2_enabled: bool
    reminder_2_days: int
    reminder_2_subject: str
    reminder_3_enabled: bool
    reminder_3_days: int
    reminder_3_subject: str
    is_active: bool
    stop_on_view: bool
    stop_on_payment: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReminderConfigUpdate(BaseModel):
    reminder_1_enabled: Optional[bool] = None
    reminder_1_days: Optional[int] = None
    reminder_1_subject: Optional[str] = None
    reminder_2_enabled: Optional[bool] = None
    reminder_2_days: Optional[int] = None
    reminder_2_subject: Optional[str] = None
    reminder_3_enabled: Optional[bool] = None
    reminder_3_days: Optional[int] = None
    reminder_3_subject: Optional[str] = None
    is_active: Optional[bool] = None
    stop_on_view: Optional[bool] = None
    stop_on_payment: Optional[bool] = None


class ReminderLogRead(BaseModel):
    id: UUID
    document_id: UUID
    reminder_level: int
    status: str
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}