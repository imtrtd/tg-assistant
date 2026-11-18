from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Хранит время как UTC без пояса, отдаёт aware datetime в UTC.

    SQLite не хранит часовой пояс, поэтому приводим всё к UTC явно.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Утренняя сводка: время «ЧЧ:ММ» в поясе пользователя (None — выключена) и момент следующей.
    digest_time: Mapped[str | None] = mapped_column(String(5))
    digest_next_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    # Архив чатов (Telegram Business): присылать ли изменённые и удалённые сообщения.
    notify_edits: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    notify_deletes: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    # Текст в нижнем регистре для поиска: lower()/LIKE в SQLite не понимают кириллицу.
    search_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_active_remind_at", "active", "remind_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    remind_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # None — однократное; иначе daily / weekdays / weekly (см. reminders.timeparse)
    repeat: Mapped[str | None] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessConnection(Base):
    """Подключение бота к аккаунту пользователя через Telegram Business."""

    __tablename__ = "business_connections"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ArchivedMessage(Base):
    """Сообщение из личного чата владельца, полученное через Telegram Business."""

    __tablename__ = "archived_messages"
    __table_args__ = (
        UniqueConstraint("owner_id", "chat_id", "message_id"),
        Index("ix_archived_messages_owner_chat_sent", "owner_id", "chat_id", "sent_at"),
        Index("ix_archived_messages_owner_deleted", "owner_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_title: Mapped[str] = mapped_column(String(256))
    message_id: Mapped[int] = mapped_column(BigInteger)
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_name: Mapped[str] = mapped_column(String(256))
    outgoing: Mapped[bool] = mapped_column(Boolean)
    text: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(32))
    file_id: Mapped[str | None] = mapped_column(String(256))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class MessageEdit(Base):
    """Прежняя версия текста сообщения до правки."""

    __tablename__ = "message_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("archived_messages.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str | None] = mapped_column(Text)
    replaced_at: Mapped[datetime] = mapped_column(UTCDateTime)


class UserTopic(Base):
    """Постоянная тема в личном чате с ботом (режим тем Telegram)."""

    __tablename__ = "user_topics"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    thread_id: Mapped[int] = mapped_column(BigInteger)
    # Закреплённое сообщение темы (у «Приложения» — с кнопкой мини-приложения).
    message_id: Mapped[int | None] = mapped_column(BigInteger)


class ClusterNode(Base):
    """Экземпляр бота (ПК, облако) при общей базе Postgres.

    Узлы раз в несколько секунд отмечаются здесь; работает только лидер, а узел с большим
    приоритетом забирает лидерство, как только появляется. См. tg_assistant.leader.
    """

    __tablename__ = "cluster_nodes"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    priority: Mapped[int] = mapped_column(default=0)
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
