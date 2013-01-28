# -*- coding:utf-8 -*-

import sae
import sae.kvdb
import sae.taskqueue
import tornado.wsgi

import os
import urllib
import logging
import hashlib
import functools

#import the main part and third-part libs for the app
from libs import alpha
from libs import PyFetion

NEW_COURSES_TEMPLATE = u'''Hello，%s！有%d门课出分了，分别是%s。%s。[Noven]'''
VCODE_MESSAGE_TEMPLATE = u'''Hello，%s！您的登记验证码为【%s】 [Noven]'''

def authenticated(method):
    """Decorate methods with this to require that the user be logged in."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.current_user:
            self.clear_all_cookies()
            self.redirect("/")
            return
        return method(self, *args, **kwargs)
    return wrapper


class BaseHandler(tornado.web.RequestHandler):
    def initialize(self):
        self.kv = kv

    def get_current_user(self):
        try:
            return self.kv.get(self.get_secure_cookie("uc"))
        except:
            pass


class SignupHandler(BaseHandler):
    def get(self):
        self.render("signup.html")

    def post(self):
        userinfo = {
            "ucode": self.get_argument("uc", None),
            "upswd": self.get_argument("up", None),
            "mcode": self.get_argument("mc", None),
            "mpswd": self.get_argument("mp", None)
        }
        self.set_secure_cookie("uc", userinfo["ucode"])
        new_user = alpha.User(
            userinfo["ucode"],
            userinfo["upswd"],
            userinfo["mcode"],
            userinfo["mpswd"]
        )
        if new_user.name and self.kv.add(new_user.usercode.encode("utf-8"), new_user):    #set() only takes str as key, WTF!
            self.redirect("/verify")
        else:
            self.redirect("/sorry")


class VerifyHandler(BaseHandler):
    @authenticated
    def get(self):
        self.render("verify.html")
        veryinfo = {
            "n": self.current_user.mobileno,
            "p": self.current_user.mobilepass,
            "c": (VCODE_MESSAGE_TEMPLATE % (self.current_user.name, hashlib.md5(self.current_user.usercode).hexdigest()[:6])).encode("utf-8")
        }
        sae.taskqueue.add_task("send_verify_sms_task", "/backend/sms", urllib.urlencode(veryinfo))

    def post(self):
        vcode = self.get_argument("vcode", None)

        if vcode == hashlib.md5(self.current_user.usercode).hexdigest()[:6]:
            self.current_user.verified = True
            self.kv.set(self.current_user.usercode.encode("utf-8"), self.current_user)
            self.redirect("/welcome")
        else:
            self.redirect("/sorry")


class WelcomeHandler(BaseHandler):
    @authenticated
    def get(self):
        if self.current_user.verified:
            self.render("welcome.html")
        else:
            self.redirect("/")


class SorryHandler(BaseHandler):
    def get(self):
        error = "请检查你的学号、密码、手机号、飞信密码及验证码是否输入有误。"
        self.render("sorry.html", error = error)


class UpdateTaskHandler(BaseHandler):
    def get(self):
        userlist = self.kv.get_by_prefix("")
        for ut in userlist:
            u = ut[1]
            # self.write(str(u.verified))
            if not u.verified or not u.name:
                continue

            new_courses = u.refresh()
            if new_courses is not None:
                try:
                    self.kv.set(u.usercode, u)
                except:
                    print "Failed to save the latest data."

                tosend = u"、".join([u"%s(%s)" % (v.subject, v.grade) for v in new_courses.values()])

                noteinfo = {
                    "n": u.mobileno,
                    "p": u.mobilepass,
                    "c": (NEW_COURSES_TEMPLATE % (u.name, len(new_courses), tosend, u.rank+u"，"+u.GPA)).encode("utf-8")
                }
                sae.taskqueue.add_task("send_notification_sms_task", "/backend/sms", urllib.urlencode(noteinfo))


class SMSTaskHandler(BaseHandler):
    def post(self):
        n = self.get_argument("n").encode("utf-8") #mobile number
        p = self.get_argument("p").encode("utf-8") #fetion password
        c = self.get_argument("c").encode("utf-8") #SMS content

        fetion = PyFetion.PyFetion(n, p, "HTTP", debug=False)
        while True:
            try:
                fetion.login()
                fetion.send_sms(c)
                fetion.logout()
            except PyFetion.PyFetionAuthError, e:
                print str(e) + " when sending to " + n
                return
            except Exception, e:
                print str(e) + " when sending to " + n
                continue
            break

        print "SMS sent to %s" % n


settings = {
    'debug': True,
    "sitename": "Noven",
    "template_path": os.path.join(os.path.dirname(__file__), "templates"),
    "static_path": os.path.join(os.path.dirname(__file__), "statics"),
    "xsrf_cookies": False,
    "cookie_secret": "NovWeMetAndThenIFa11emberWLY/==",
    "autoescape": None,
    "login_url": "/"
}


app = tornado.wsgi.WSGIApplication([
    (r"/", SignupHandler),
    (r"/welcome", WelcomeHandler),
    (r"/verify", VerifyHandler),
    (r"/sorry", SorryHandler),
    (r"/backend/update", UpdateTaskHandler),
    (r"/backend/sms", SMSTaskHandler),
], **settings)


kv = sae.kvdb.KVClient()
# logging.basicConfig(format='%(asctime)s - %(levelname)-8s %(message)s', level=logging.DEBUG)
application = sae.create_wsgi_app(app)