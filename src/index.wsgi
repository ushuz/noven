# -*- coding:utf-8 -*-

import sae
import tornado.wsgi

import os
import logging

#import handlers
import noven    # main logic
import admin    # administration


settings = {
    'debug': True,
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

app = tornado.wsgi.WSGIApplication([
    (r"/", noven.SignupHandler),
    (r"/welcome", noven.WelcomeHandler),
    (r"/verify", noven.VerifyHandler),
    (r"/sorry", noven.SorryHandler),
    (r"/weixin", noven.WxHandler),
    
    (r"/backend/update", noven.UpdateTaskHandler),
    (r"/backend/sms", noven.SMSTaskHandler),
    (r"/backend/upgrade", noven.UpgradeHandler),

    (r"/admin", admin.Main),
    (r"/admin/user/([0-9]*)", admin.UsersManagement),
    (r"/admin/msg", admin.GroupMessage)
], **settings)

# logging.basicConfig(format='%(asctime)s - %(levelname)-8s %(message)s', level=logging.DEBUG)
application = sae.create_wsgi_app(app)