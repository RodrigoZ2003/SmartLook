import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "smartlook-secret-key-ciclo1-2026"
)

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:4200")

# NUEVO (CU15): credenciales de Stripe (modo test).
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

# NUEVO (CU21): delivery. La clave de OpenRouteService va en variable de
# entorno (nunca en el código). Las tarifas son valores de ejemplo y se pueden
# cambiar por variable de entorno sin tocar código.
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
DELIVERY_TARIFA_BASE = float(os.getenv("DELIVERY_TARIFA_BASE", "8"))
DELIVERY_TARIFA_KM = float(os.getenv("DELIVERY_TARIFA_KM", "2.5"))
DELIVERY_PRENDAS_INCLUIDAS = int(os.getenv("DELIVERY_PRENDAS_INCLUIDAS", "3"))
DELIVERY_RECARGO_PRENDA = float(os.getenv("DELIVERY_RECARGO_PRENDA", "1"))
DELIVERY_RADIO_MAX_KM = float(os.getenv("DELIVERY_RADIO_MAX_KM", "25"))
# NUEVO (CU18/19/20): asistente de IA. Las claves van en variables de entorno
# (nunca en el código). Groq es el proveedor principal y Gemini el respaldo.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
AI_TIMEOUT_SEG = int(os.getenv("AI_TIMEOUT_SEG", "15"))

DEBUG = False

ALLOWED_HOSTS = ["*"]


INSTALLED_APPS = [

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Terceros
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",

    # Apps locales
    "apps.users_auth",
    "apps.catalog",
    "apps.inventory",
    "apps.reservations",
    "apps.sales",
    "apps.innovation",
    "apps.bi_reports",
    # NUEVO (Fase 3 - CU09): analítica con Machine Learning.
    "apps.analytics",
]


MIDDLEWARE = [

    "django.middleware.security.SecurityMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",

    "corsheaders.middleware.CorsMiddleware",

    "django.middleware.common.CommonMiddleware",

    "django.middleware.csrf.CsrfViewMiddleware",

    "django.contrib.auth.middleware.AuthenticationMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",

    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # Registra en Bitácora cada POST/PUT/PATCH/DELETE de un usuario
    # autenticado (compras, reservas, altas, etc).
    "common.middleware.audit_middleware.AuditMiddleware",
]


ROOT_URLCONF = "config.urls"


TEMPLATES = [

    {

        "BACKEND":
            "django.template.backends.django.DjangoTemplates",

        "DIRS": [],

        "APP_DIRS": True,

        "OPTIONS": {

            "context_processors": [

                "django.template.context_processors.debug",

                "django.template.context_processors.request",

                "django.contrib.auth.context_processors.auth",

                "django.contrib.messages.context_processors.messages",

            ],

        },

    },

]


WSGI_APPLICATION = "config.wsgi.application"

ASGI_APPLICATION = "config.asgi.application"


DATABASES = {

    "default": {

        "ENGINE":
            "django.db.backends.postgresql",

        "NAME":
            os.getenv(
                "DB_NAME",
                "smartlook_db"
            ),

        "USER":
            os.getenv(
                "DB_USER",
                "postgres"
            ),

        "PASSWORD":
            os.getenv(
                "DB_PASSWORD",
                "postgres"
            ),

        "HOST":
            os.getenv(
                "DB_HOST",
                "localhost"
            ),

        "PORT":
            os.getenv(
                "DB_PORT",
                "5432"
            ),

    }

}


AUTH_PASSWORD_VALIDATORS = [

    {

        "NAME":
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",

    },

    {

        "NAME":
            "django.contrib.auth.password_validation.MinimumLengthValidator",

    },

    {

        "NAME":
            "django.contrib.auth.password_validation.CommonPasswordValidator",

    },

    {

        "NAME":
            "django.contrib.auth.password_validation.NumericPasswordValidator",

    },

]


LANGUAGE_CODE = "es-bo"

TIME_ZONE = "America/La_Paz"

USE_I18N = True

USE_TZ = True


STATIC_URL = "static/"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"



# Django REST Framework

REST_FRAMEWORK = {

    "DEFAULT_AUTHENTICATION_CLASSES": [

        "apps.users_auth.authentication.SmartLookJWTAuthentication",

    ],

    "DEFAULT_PERMISSION_CLASSES": [

        "rest_framework.permissions.IsAuthenticated",

    ],

    "DEFAULT_PAGINATION_CLASS":

        "common.pagination.StandardPagination",

    "PAGE_SIZE": 20,

    "DEFAULT_SCHEMA_CLASS":

        "drf_spectacular.openapi.AutoSchema",

}



# Simple JWT

from datetime import timedelta


SIMPLE_JWT = {

    "ACCESS_TOKEN_LIFETIME":

        timedelta(hours=2),

    "REFRESH_TOKEN_LIFETIME":

        timedelta(days=7),

    "ROTATE_REFRESH_TOKENS":

        True,

    "BLACKLIST_AFTER_ROTATION":

        True,

    "AUTH_HEADER_TYPES":

        (

            "Bearer",

        ),

}



# CORS

CORS_ALLOWED_ORIGINS = [

    origin.strip()

    for origin in os.getenv(

        "CORS_ALLOWED_ORIGINS",

        ""

    ).split(",")

    if origin.strip()

]



# DRF Spectacular

SPECTACULAR_SETTINGS = {

    "TITLE":

        "SmartLook API",

    "DESCRIPTION":

        "Sistema omnicanal e-commerce y POS multi-sucursal",

    "VERSION":

        "1.0.0",

    "SERVE_INCLUDE_SCHEMA":

        False,

    "COMPONENT_SPLIT_REQUEST":

        True,

    "APPEND_COMPONENTS": {

        "securitySchemes": {

            "jwtAuth": {

                "type":

                    "http",

                "scheme":

                    "bearer",

                "bearerFormat":

                    "JWT",

            }

        }

    },

    "SECURITY": [

        {

            "jwtAuth": []

        }

    ],

    "SWAGGER_UI_SETTINGS": {

        "deepLinking":

            True,

        "persistAuthorization":

            True,

    },

}