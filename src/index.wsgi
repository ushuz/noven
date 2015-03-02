# -*- coding:utf-8 -*-

import httplib
import logging
import os

import sae
import tornado.wsgi

# Import handlers
import noven    # Main logic
import admin    # Administration
import api


settings = {
    "debug": False,
    "gzip": True,
    "sitename": "Noven",
    "template_path": os.path.join(os.path.dirname(__file__), "templates"),
    "static_path": os.path.join(os.path.dirname(__file__), "static"),
    "xsrf_cookies": True,
    "cookie_secret": "NovWeMetAndThenIFa11emberWLY/==",
    "autoescape": None,
    "login_url": "/"
}

handlers = [
    (r"/", noven.HomeHandler),
    (r"/verify", noven.VerifyHandler),
    (r"/welcome", noven.WelcomeHandler),
    (r"/weixin", noven.WxHandler),
    (r"/mine", noven.ReportHandler),

    (r"/backend/update", noven.UpdateAll),
    (r"/backend/update/([0-9]{9,10})", noven.UpdateById),
    (r"/backend/sms/([0-9]{9,10})", noven.SMSById),
    (r"/backend/notie", noven.NotieHandler),
    (r"/backend/summary", noven.SummaryHandler),

    (r"/admin", admin.Main),
    (r"/admin/user/([0-9]{9,10})", admin.UsersManagement),
    (r"/admin/msg", admin.GroupMessage)
]

# Customized Error Code
httplib.responses.update({
    421: "User Auth Failed",
    422: "Mobile Auth Failed",
    423: "Mobile Not Supported",
    424: "Duplicate Sign Up",
    425: "Not Activated",
    426: "Blocked",
    427: "Verification Required",
    444: "Unknown",
})

if "SERVER_SOFTWARE" not in os.environ:
    # Enable debug mode
    # Template will autoreload in debug mode
    settings["debug"] = True

    # Local static path
    settings["static_path"] = os.path.join(os.path.dirname(__file__), "../assets")

    # Disable CSRF defense in convenience of testing
    settings["xsrf_cookies"] = False

    # Debug logging settings
    logging.basicConfig(format="%(asctime)s.%(msecs)0.3d - %(levelname)s [%(name)s] %(message)s", level=logging.DEBUG, datefmt="%H:%M:%S")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # API under testing
    # Future users api, returning json.
    handlers.append((r"/api/users", api.Users))
    handlers.append((r"/api/users/([0-9]{9,10})", api.UserById))

    # Utilities for test
    import util
    # Handler for temporarily use
    handlers.append((r"/util/something", util.Temp))
    # Interface for KVDB
    handlers.append((r"/util/kv", util.KVDB))
    # Generate signatures used for testing
    handlers.append((r"/util/kg", util.KeyGen))
    # Render the given template
    handlers.append((r"/(.+?).html", util.UIDebug))

# Global logging settings
logging.basicConfig(format="%(levelname)s [%(name)s] %(message)s", level=logging.INFO)
logging.getLogger("libs.requests").setLevel(logging.WARNING)
logging.getLogger("libs.NovenFetion").setLevel(logging.WARNING)

app = tornado.wsgi.WSGIApplication(handlers, **settings)
application = sae.create_wsgi_app(app)
