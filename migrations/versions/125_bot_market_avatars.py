"""Migration 125: give already-installed market bots their catalog avatar.

Market cards have always carried an emoji icon, but install used to write an
empty avatar, so an installed Bot fell back to its deterministic letter mark.
This backfill sets the emoji avatar only where the bot still has the empty
avatar; a reader's later pick is never overwritten.
"""

from alembic import op

revision = "125"
down_revision = "124"
branch_labels = None
depends_on = None

#: The built-in catalogue's icons at the time of this migration. Installing a
#: new market Bot writes its icon directly; this list is only the history.
_CATALOG_ICONS = """
      ('a-share-researcher', '🔎'),
      ('earnings-analyst', '📊'),
      ('market-reviewer', '🌅'),
      ('event-researcher', '🧭'),
      ('risk-reviewer', '🛡️'),
      ('uzi-buffett', '🏛️'),
      ('uzi-graham', '🏛️'),
      ('uzi-fisher', '🏛️'),
      ('uzi-munger', '🏛️'),
      ('uzi-templeton', '🏛️'),
      ('uzi-klarman', '🏛️'),
      ('uzi-lynch', '🌱'),
      ('uzi-oneill', '🌱'),
      ('uzi-thiel', '🌱'),
      ('uzi-wood', '🌱'),
      ('uzi-andreessen', '🌱'),
      ('uzi-gurley', '🌱'),
      ('uzi-naval', '🌱'),
      ('uzi-gerstner', '🌱'),
      ('uzi-chamath', '🌱'),
      ('uzi-soros', '🌍'),
      ('uzi-dalio', '🌍'),
      ('uzi-marks', '🌍'),
      ('uzi-druck', '🌍'),
      ('uzi-robertson', '🌍'),
      ('uzi-burry', '🌍'),
      ('uzi-chanos', '🌍'),
      ('uzi-livermore', '📈'),
      ('uzi-minervini', '📈'),
      ('uzi-darvas', '📈'),
      ('uzi-gann', '📈'),
      ('uzi-duan', '🀄'),
      ('uzi-zhangkun', '🀄'),
      ('uzi-zhushaoxing', '🀄'),
      ('uzi-xiezhiyu', '🀄'),
      ('uzi-fengliu', '🀄'),
      ('uzi-dengxiaofeng', '🀄'),
      ('uzi-zhang-lei', '🀄'),
      ('uzi-zhang-mz', '🐉'),
      ('uzi-sun-ge', '🐉'),
      ('uzi-zhao-lg', '🐉'),
      ('uzi-fs-wyj', '🐉'),
      ('uzi-yangjia', '🐉'),
      ('uzi-chen-xq', '🐉'),
      ('uzi-hu-jl', '🐉'),
      ('uzi-fang-xx', '🐉'),
      ('uzi-zuoshou', '🐉'),
      ('uzi-xiao-ey', '🐉'),
      ('uzi-jiao-yy', '🐉'),
      ('uzi-mao-lb', '🐉'),
      ('uzi-xiao-xian', '🐉'),
      ('uzi-lasa', '🐉'),
      ('uzi-chengdu', '🐉'),
      ('uzi-sunan', '🐉'),
      ('uzi-ningbo-st', '🐉'),
      ('uzi-liuyi-zl', '🐉'),
      ('uzi-liu-sh', '🐉'),
      ('uzi-gu-bl', '🐉'),
      ('uzi-bj-cj', '🐉'),
      ('uzi-wang-zr', '🐉'),
      ('uzi-xin-dd', '🐉'),
      ('uzi-ghzw', '🐉'),
      ('uzi-simons', '🧮'),
      ('uzi-thorp', '🧮'),
      ('uzi-shaw', '🧮'),
      ('uzi-asness', '🧮'),
      ('uzi-jensen-huang', '🚀'),
      ('uzi-musk', '🚀'),
      ('uzi-altman', '🚀'),
      ('uzi-saylor', '🚀'),
      ('uzi-serenity', '🤖')
"""


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        f"""
        UPDATE bots AS b
        SET avatar = jsonb_build_object('kind', 'emoji', 'emoji', v.icon)
        FROM bot_market_installs AS i
        JOIN (VALUES
{_CATALOG_ICONS}
        ) AS v(slug, icon) ON i.listing_slug = v.slug
        WHERE i.bot_id = b.bot_id
          AND (b.avatar IS NULL OR b.avatar = '{{}}'::jsonb)
        """
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    # An emoji avatar may already be the reader's own choice; do not remove it.
    pass
