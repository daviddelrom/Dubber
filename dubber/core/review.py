from dataclasses import dataclass

from .matching import ReviewGroup
from .mkv import MediaMetadata


@dataclass(frozen=True)
class ConfirmedGroup:
    group_id: str
    members: list[MediaMetadata]


@dataclass(frozen=True)
class ReviewError:
    message: str


def resolve_review_group(
    group: ReviewGroup, partition: list[list[str]]
) -> list[ConfirmedGroup] | ReviewError:
    member_ids = [member.identity.file_id for member in group.members]
    if not member_ids or len(member_ids) != len(set(member_ids)):
        return ReviewError("El grupo de revisión contiene identidades no válidas")
    if not isinstance(partition, list) or not partition:
        return ReviewError("La partición debe incluir todos los archivos del grupo")
    if any(not isinstance(part, list) or not part for part in partition):
        return ReviewError("Cada grupo de la partición debe contener archivos")

    members_by_id = {
        member.identity.file_id: member for member in group.members
    }
    seen_ids = set()
    for part in partition:
        for file_id in part:
            if not isinstance(file_id, str) or file_id not in members_by_id:
                return ReviewError(f"Identidad desconocida en la partición: {file_id}")
            if file_id in seen_ids:
                return ReviewError(f"Identidad duplicada en la partición: {file_id}")
            seen_ids.add(file_id)
    if seen_ids != set(member_ids):
        return ReviewError("La partición debe incluir cada archivo exactamente una vez")

    resolved = []
    for index, part in enumerate(partition):
        group_id = (
            group.group_id
            if len(partition) == 1
            else f"{group.group_id}-part-{index + 1}"
        )
        resolved.append(
            ConfirmedGroup(
                group_id=group_id,
                members=[members_by_id[file_id] for file_id in part],
            )
        )
    return resolved
