"""Allow independently configured chat connections for prompt planning."""
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("model_connections_protocol_check", "model_connections", schema="generation_config", type_="check")
    op.create_check_constraint("model_connections_protocol_check", "model_connections", "protocol IN ('openai_images', 'openai_chat')", schema="generation_config")


def downgrade():
    # Preserve immutable chat records; fail safely if they prevent a downgrade.
    op.drop_constraint("model_connections_protocol_check", "model_connections", schema="generation_config", type_="check")
    op.create_check_constraint("model_connections_protocol_check", "model_connections", "protocol = 'openai_images'", schema="generation_config")
