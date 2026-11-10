"""Каталог установленных блоков для редактора."""

from fastapi import APIRouter

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.schemas import BlockCatalogItem

router = APIRouter(prefix="/blocks", tags=["Блоки"], responses=REFUSALS)


@router.get("", summary="Каталог блоков")
async def list_blocks(teacher: Teacher, assembly: Assembled) -> list[BlockCatalogItem]:
    manifests = assembly.registry.manifests
    return [BlockCatalogItem.of(manifests[key]) for key in sorted(manifests)]
