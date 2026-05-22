"""Copy only the packages needed for LiteLLM proxy with OpenAI + Anthropic."""
import fnmatch
import os
import shutil
import site

src = site.getsitepackages()[0]
dst = "/opt/venv/lib/python3.12/site-packages"

# Heavy packages to SKIP (these account for ~3-4 GB of the 5.6 GB image)
SKIP_PATTERNS = [
    # Cloud SDKs we don't use
    "*google_cloud_aiplatform*",
    "*google_cloud_storage*",
    "*google_cloud_bigquery*",
    "*google_cloud_resource_manager*",
    "*google_cloud_core*",
    "*google_cloud_kms*",
    "*google_cloud_iam*",
    "*google_genai*",
    "*google_crc32c*",
    "*google_resumable_media*",
    "*googleapis_common_protos*",
    "*grpc_google_iam_v1*",
    "*grpc_status*",
    "*grpcio*",
    "*grpcio_status*",
    "*azure_identity*",
    "*azure_keyvault*",
    "*azure_storage*",
    "*azure_core*",
    "*azure_ai_contentsafety*",
    "*azure_storage_file_datalake*",
    "*boto3*",
    "*botocore*",
    "*s3transfer*",
    "*aiobotocore*",
    "*aioboto3*",
    "*aioitertools*",
    # Heavy data/ML packages
    "*polars*",
    "*numpy*",
    "*numpy.libs*",
    "*ml_dtypes*",
    "*vertexai*",
    "*vertex_ray*",
    # Telemetry/monitoring
    "*ddtrace*",
    "*envier*",
    "*bytecode*",
    "*sentry_sdk*",
    "*opentelemetry*",
    "*prometheus_client*",
    "*pyroscope*",
    # LLM sandbox / semantic router
    "*llm_sandbox*",
    "*semantic_router*",
    "*detect_secrets*",
    # OpenAPI validation (not needed for proxy)
    "*openapi_core*",
    "*openapi_schema_validator*",
    "*openapi_spec_validator*",
    "*jsonschema_path*",
    "*pathable*",
    # Other unused
    "*aurelio_sdk*",
    "*pypdf*",
    "*pillow*",
    "*pillow.libs*",
    "*colorlog*",
    "*supervisor*",
    "*tornado*",
    "*mangum*",
    "*legacy_cgi*",
    "*cgi.py",
    "*cgitb.py",
    "*rfc3339_validator*",
    "*xmltodict*",
    "*lazy_object_proxy*",
    "*wrapt*",
    "*docstring_parser*",
    "*more_itertools*",
    "*jaraco*",
    "*deprecated*",
    "*requests_toolbelt*",
    "*async_generator*",
    "*tzdata*",
    "*pytz*",
    "*distutils-precedence.pth",
    "*coloredlogs.pth",
    "*nodejs_wheel*",
    "*PIL*",
    "*_soundfile*",
    "*_soundfile_data*",
    "*_distutils_hack*",
    "*__pycache__",
    "*81d243bd2c585b0f4821__mypyc*",
]

os.makedirs(dst, exist_ok=True)

for item in sorted(os.listdir(src)):
    # Skip if matches a skip pattern
    if any(fnmatch.fnmatch(item, pat) for pat in SKIP_PATTERNS):
        continue

    # Keep everything else
    item_path = os.path.join(src, item)
    dst_path = os.path.join(dst, item)
    if os.path.isdir(item_path):
        shutil.copytree(item_path, dst_path, dirs_exist_ok=True)
    else:
        shutil.copy2(item_path, dst_path)

print(f"Done — copied needed packages to {dst}")
