#!/usr/bin/env python3
# The MIT License (MIT)
# © 2024 templar.tech

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Find and load the correct .env file
env_path = Path(__file__).parent.parent / ".env"
if not env_path.exists():
    raise FileNotFoundError(f"Required .env file not found at {env_path}")

# Load environment variables before any other imports
load_dotenv(env_path, override=True)

from aiobotocore.session import get_session
from tplr import logger, __version__

# Add parent directory to path to import tplr
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tplr


async def cleanup_version():
    """Delete objects in R2 bucket that match the current version pattern"""
    # Load environment variables
    load_dotenv()

    # Validate required environment variables
    required_vars = [
        "R2_GRADIENTS_ACCOUNT_ID",
        "R2_GRADIENTS_WRITE_ACCESS_KEY_ID",
        "R2_GRADIENTS_WRITE_SECRET_ACCESS_KEY",
    ]

    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Get credentials from environment
    account_id = os.environ["R2_GRADIENTS_ACCOUNT_ID"]
    access_key_id = os.environ["R2_GRADIENTS_WRITE_ACCESS_KEY_ID"]
    secret_access_key = os.environ["R2_GRADIENTS_WRITE_SECRET_ACCESS_KEY"]

    # Version pattern to match
    version_pattern = f"-v{__version__}"
    logger.info(f"Looking for files with version pattern: {version_pattern}")

    # Initialize S3 client
    session = get_session()
    async with session.create_client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="enam",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=tplr.config.client_config,
    ) as client:
        logger.info("Listing objects in bucket...")

        # Use paginator to handle buckets with >1000 objects
        paginator = client.get_paginator("list_objects_v2")
        objects_to_delete = []

        try:
            async for page in paginator.paginate(Bucket=account_id):
                if "Contents" in page:
                    # Filter objects that match version pattern and are checkpoints, start.json, or gradients
                    filtered_objects = [
                        {"Key": obj["Key"]}
                        for obj in page["Contents"]
                        if version_pattern in obj["Key"] and any(
                            prefix in obj["Key"]
                            for prefix in ["checkpoint", "start", "gradient"]
                        )
                    ]
                    objects_to_delete.extend(filtered_objects)

            if not objects_to_delete:
                logger.info(f"No files found matching version {__version__}")
                return

            # Delete objects in batches of 1000 (S3 limit)
            batch_size = 1000
            for i in range(0, len(objects_to_delete), batch_size):
                batch = objects_to_delete[i : i + batch_size]
                logger.info(f"Deleting batch of {len(batch)} objects...")

                response = await client.delete_objects(
                    Bucket=account_id, Delete={"Objects": batch}
                )

                # Log any errors
                if "Errors" in response:
                    for error in response["Errors"]:
                        logger.error(
                            f"Error deleting {error['Key']}: {error['Message']}"
                        )

            logger.success(
                f"Successfully deleted {len(objects_to_delete)} files matching version {__version__}"
            )

        except Exception as e:
            logger.error(f"Error cleaning up version files: {e}")
            sys.exit(1)


if __name__ == "__main__":
    logger.info(f"Starting cleanup of files matching version {__version__}...")
    asyncio.run(cleanup_version())