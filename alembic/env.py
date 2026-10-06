from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base, UTCDateTime

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    return True


def render_item(type_, obj, autogen_context):
    """`UTCDateTime` (bir `TypeDecorator`, bkz. app/models.py) autogenerate
    tarafından script'e gömülürken varsayılan olarak `app.models.
    UTCDateTime(...)` diye yazılır — migration dosyası `app.models`'ı hiç
    import etmediği için bu `NameError` ile patlar. DDL açısından zaten
    `impl`'i (`DateTime(timezone=True)`) ile birebir aynı olduğu için
    (yalnızca Python tarafında okurken tzinfo düzeltmesi yapıyor, DDL'i
    değiştirmiyor) burada onun yerine hep `sa.DateTime(timezone=True)`
    render ediyoruz — hem çalışır hem de ekstra bir import gerekmez."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
