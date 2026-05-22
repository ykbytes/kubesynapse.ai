"""Patch litellm to remove heavy-dependency imports (boto3, azure, gcs, otel).

Patches:
1. custom_logger_registry.py — removes logger classes that pull heavy deps.
2. focus/destinations/factory.py — wraps s3_destination import so missing boto3
   doesn't crash the entire FocusLogger import chain.
3. proxy_server.py — wraps FocusLogger import in spend-tracking init so it
   degrades gracefully when boto3 is absent.
"""
import re
import site
import os

src = site.getsitepackages()[0]

# ---------------------------------------------------------------------------
# 1. Patch custom_logger_registry.py
# ---------------------------------------------------------------------------
path = f"{src}/litellm/litellm_core_utils/custom_logger_registry.py"

with open(path, "r") as f:
    content = f.read()

# Loggers to remove (require heavy deps: boto3, azure, google-cloud, opentelemetry)
# Also remove loggers that TRANSITIVELY import these (e.g. VantageLogger → FocusLogger → boto3)
REMOVE_IMPORTS = [
    "from litellm.integrations.focus.focus_logger import FocusLogger",
    "from litellm.integrations.vantage.vantage_logger import VantageLogger",
    "from litellm.integrations.s3_v2 import S3Logger",
    "from litellm.integrations.sqs import SQSLogger",
    "from litellm.integrations.azure_storage.azure_storage import AzureBlobStorageLogger",
    "from litellm.integrations.gcs_bucket.gcs_bucket import GCSBucketLogger",
    "from litellm.integrations.gcs_pubsub.pub_sub import GcsPubSubLogger",
    "from litellm.integrations.opentelemetry import OpenTelemetry",
]

# Remove import lines
for imp in REMOVE_IMPORTS:
    content = content.replace(imp + "\n", "")

# Remove registry entries
REMOVE_ENTRIES = [
    '"focus": FocusLogger,',
    '"vantage": VantageLogger,',
    '"s3_v2": S3Logger,',
    '"aws_sqs": SQSLogger,',
    '"azure_storage": AzureBlobStorageLogger,',
    '"gcs_bucket": GCSBucketLogger,',
    '"gcs_pubsub": GcsPubSubLogger,',
    '"opentelemetry": OpenTelemetry,',
    '"logfire": OpenTelemetry,',
    '"arize": OpenTelemetry,',
    '"langfuse_otel": OpenTelemetry,',
    '"arize_phoenix": OpenTelemetry,',
    '"langtrace": OpenTelemetry,',
    '"weave_otel": OpenTelemetry,',
    '"levo": OpenTelemetry,',
    '"otel": OpenTelemetry,',
]

for entry in REMOVE_ENTRIES:
    content = content.replace("        " + entry + "\n", "")

with open(path, "w") as f:
    f.write(content)

print(f"[1/3] Patched {path}")

# ---------------------------------------------------------------------------
# 2. Patch focus/destinations/factory.py — make s3_destination import optional
# ---------------------------------------------------------------------------
factory_path = f"{src}/litellm/integrations/focus/destinations/factory.py"

if os.path.exists(factory_path):
    with open(factory_path, "r") as f:
        factory_content = f.read()

    # Replace unconditional s3 import with try/except
    factory_content = factory_content.replace(
        "from .s3_destination import FocusS3Destination",
        "try:\n    from .s3_destination import FocusS3Destination\nexcept ImportError:\n    FocusS3Destination = None  # boto3 not installed",
    )

    with open(factory_path, "w") as f:
        f.write(factory_content)

    print(f"[2/5] Patched {factory_path}")
else:
    print(f"[2/5] Skipped (not found): {factory_path}")

# ---------------------------------------------------------------------------
# 3. Patch focus/destinations/__init__.py — make s3 import conditional
# ---------------------------------------------------------------------------
dest_init_path = f"{src}/litellm/integrations/focus/destinations/__init__.py"

if os.path.exists(dest_init_path):
    with open(dest_init_path, "r") as f:
        dest_init_content = f.read()

    # Replace unconditional s3 import with try/except
    dest_init_content = dest_init_content.replace(
        "from .s3_destination import FocusS3Destination",
        "try:\n    from .s3_destination import FocusS3Destination\nexcept ImportError:\n    FocusS3Destination = None  # boto3 not installed",
    )

    with open(dest_init_path, "w") as f:
        f.write(dest_init_content)

    print(f"[3/5] Patched {dest_init_path}")
else:
    print(f"[3/5] Skipped (not found): {dest_init_path}")

# ---------------------------------------------------------------------------
# 4. Patch focus/focus_logger.py — wrap destinations import in try/except
# ---------------------------------------------------------------------------
focus_logger_path = f"{src}/litellm/integrations/focus/focus_logger.py"

if os.path.exists(focus_logger_path):
    with open(focus_logger_path, "r") as f:
        focus_logger_content = f.read()

    # Wrap destinations import
    focus_logger_content = focus_logger_content.replace(
        "from .destinations import FocusTimeWindow",
        "try:\n    from .destinations import FocusTimeWindow\nexcept ImportError:\n    FocusTimeWindow = None  # boto3 not installed",
    )

    with open(focus_logger_path, "w") as f:
        f.write(focus_logger_content)

    print(f"[4/5] Patched {focus_logger_path}")
else:
    print(f"[4/5] Skipped (not found): {focus_logger_path}")

# ---------------------------------------------------------------------------
# 5. Patch proxy_server.py — wrap FocusLogger import in spend tracking init
# ---------------------------------------------------------------------------
proxy_path = f"{src}/litellm/proxy/proxy_server.py"

if os.path.exists(proxy_path):
    with open(proxy_path, "r") as f:
        proxy_content = f.read()

    # Wrap FocusLogger import and usage in spend tracking init
    proxy_content = proxy_content.replace(
        "        try:\n            from litellm.integrations.focus.focus_logger import FocusLogger\n        except ImportError:\n            FocusLogger = None  # boto3 not installed (slim image)\n\n        if await is_cloudzero_setup():\n            await CloudZeroLogger.init_cloudzero_background_job(scheduler=scheduler)\n\n        ########################################################\n        # Focus Background Job\n        ########################################################\n        await FocusLogger.init_focus_export_background_job(scheduler=scheduler)",
        "        try:\n            from litellm.integrations.focus.focus_logger import FocusLogger\n        except ImportError:\n            FocusLogger = None  # boto3 not installed (slim image)\n        from litellm.proxy.spend_tracking.cloudzero_endpoints import is_cloudzero_setup\n\n        if await is_cloudzero_setup():\n            await CloudZeroLogger.init_cloudzero_background_job(scheduler=scheduler)\n\n        ########################################################\n        # Focus Background Job\n        ########################################################\n        if FocusLogger is not None:\n            await FocusLogger.init_focus_export_background_job(scheduler=scheduler)",
    )

    with open(proxy_path, "w") as f:
        f.write(proxy_content)

    print(f"[3/3] Patched {proxy_path}")
else:
    print(f"[3/3] Skipped (not found): {proxy_path}")

print("\nAll patches applied successfully.")
