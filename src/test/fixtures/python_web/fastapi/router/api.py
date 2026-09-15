from fastapi import APIRouter

router = APIRouter()


@router.api_route("/bulk", methods=["POST", "PUT"], description="fixture bulk description")
def bulk_items():
    return []
