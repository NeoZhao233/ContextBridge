from dataclasses import dataclass


@dataclass
class TokenFamily:
    active_token: str
    revoked: bool = False


class RefreshTokenStore:
    def __init__(self) -> None:
        self._families: dict[str, TokenFamily] = {}

    def issue(self, family_id: str, token: str) -> None:
        self._families[family_id] = TokenFamily(active_token=token)

    def exchange(self, family_id: str, presented_token: str, next_token: str) -> None:
        family = self._families[family_id]
        if family.revoked:
            raise ValueError("token family revoked")
        if presented_token != family.active_token:
            # Replay policy is deliberately incomplete for the handoff study.
            raise ValueError("refresh token reuse")
        family.active_token = next_token
