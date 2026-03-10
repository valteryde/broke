
import os


eat_your_own_dogfood = os.environ.get("BROKE_EAT_YOUR_OWN_DOGFOOD", "false").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
dogfood_dsn = os.environ.get("BROKE_DOGFOOD_DSN", "").strip()
