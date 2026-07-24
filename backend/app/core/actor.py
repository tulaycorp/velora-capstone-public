from dataclasses import dataclass


@dataclass(frozen=True)
class ActorContext:
    organization_id: str | None
    actor_id: str
    auth_provider: str = "local"
    session_id: str | None = None
    org_role: str | None = None
    organization_slug: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    image_url: str | None = None
