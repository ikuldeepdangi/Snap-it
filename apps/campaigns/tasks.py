import logging
from django.db import transaction
from .models import Campaign, Company
from .services import CampaignGeneratorService

try:
    from celery import shared_task
except ImportError:
    def shared_task(func):
        func.delay = func
        return func

logger = logging.getLogger(__name__)


@shared_task
def generate_campaign_targets_task(campaign_id: int, target_count: int = 12):
    """
    Background Celery task to perform grounded job discovery and save
    target companies directly to the database.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
    except Campaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} does not exist.")
        return False

    try:
        exclusions = []
        if campaign.user:
            exclusions = list(
                Company.objects.filter(campaign__user=campaign.user)
                .values_list("name", flat=True)
                .distinct()
            )

        service = CampaignGeneratorService()
        raw_targets = service.generate_targets(
            tech_stack=campaign.tech or "",
            city=campaign.city or "",
            experience_tier=campaign.experience or "",
            target_count=target_count,
            exclusions=exclusions,
            user=campaign.user,
        )

        with transaction.atomic():
            company_objects = []
            for target in raw_targets:
                company_objects.append(
                    Company(
                        campaign=campaign,
                        name=target["name"],
                        website=target.get("careers_url"),
                        hr_email=target.get("hr_email"),
                        location=target.get("city") or campaign.city,
                        evidence_url=target.get("careers_url"),
                        campaign_status="PENDING",
                        is_hiring=True,
                        is_verified=bool(target.get("hr_email")),
                        verification_reason=f"Position: {target.get('job_title', '')}",
                    )
                )

            if company_objects:
                Company.objects.bulk_create(company_objects)

            campaign.status = "READY"
            campaign.save()

        logger.info(f"Successfully generated {len(raw_targets)} targets for campaign {campaign_id}.")
        return True

    except Exception as exc:
        logger.error(f"Failed to generate campaign targets for campaign {campaign_id}: {exc}", exc_info=True)
        campaign.status = "FAILED"
        campaign.save()
        return False
