# -*- coding:utf-8 -*-

import os
import logging

import sae
import tornado.wsgi

# Import handlers
import noven    # Main logic
import admin    # Administration

# Global logging settings
logging.basicConfig(format="%(levelname).1s [%(asctime).19s] %(message)s", level=logging.INFO)
logging.getLogger("libs.requests").setLevel(logging.WARNING)

settings = {
    "debug": False,
    "sitename": "Noven",
    "template_path": os.path.join(os.path.dirname(__file__), "templates"),
    "static_path": os.path.join(os.path.dirname(__file__), "static"),
    "xsrf_cookies": True,
    "cookie_secret": "NovWeMetAndThenIFa11emberWLY/==",
    "autoescape": None,
    "login_url": "/"
}

if "SERVER_SOFTWARE" not in os.environ:
    settings["static_path"] = os.path.join(os.path.dirname(__file__), "../assets")

    # Set logging level to DEBUG when run locally
    logging.getLogger().setLevel(logging.DEBUG)

app = tornado.wsgi.WSGIApplication([
    (r"/", noven.SignupHandler),
    (r"/welcome", noven.WelcomeHandler),
    (r"/verify", noven.VerifyHandler),
    (r"/sorry", noven.SorryHandler),
    (r"/weixin", noven.WxHandler),

    (r"/backend/update", noven.UpdateAll),
    (r"/backend/update/([0-9]{9,10})", noven.UpdateById),
    (r"/backend/sms/([0-9]{9,10})", noven.SMSById),
    # (r"/backend/something", noven.TempHandler),

    (r"/admin", admin.Main),
    (r"/admin/user/([0-9]{9,10})", admin.UsersManagement),
    (r"/admin/msg", admin.GroupMessage)
], **settings)

application = sae.create_wsgi_app(app)
