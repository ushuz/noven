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
from libs import alpha2 as alpha
from libs import NovenFetion

def authenticated(method):
    """Decorate methods with this to require that the user be logged in."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.current_user:
            self.render("admin_login.html")
            return
        return method(self, *args, **kwargs)
    return wrapper


class AdminHandler(tornado.web.RequestHandler):
    def initialize(self, *args, **kwargs):
        self.kv = sae.kvdb.KVClient()
    
    def get_current_user(self):
        if self.get_secure_cookie("uc") == "***REMOVED***":
            return "***REMOVED***"

    def write_error(self, status_code, **kwargs):
        if status_code == 404:
            error = "您要的东西不在这儿。"
            self.render("sorry.html", error=error)
        elif status_code >= 500:
            error = "服务器开小差了。"
            self.render("sorry.html", error=error)


class Main(AdminHandler):
    @authenticated
    def get(self):
        userlist = [ut[1] for ut in self.kv.get_by_prefix("") if isinstance(ut[1], alpha.User)]
        self.render("admin_main.html", userlist=userlist)
    
    def post(self):
        password = self.get_argument("password", None)
        print password
        if u"***REMOVED***" == password:
            self.set_secure_cookie("uc", "***REMOVED***")
            self.redirect("/admin")
        

class UsersManagement(AdminHandler):
    @authenticated
    def get(self, uc="noven"):
        u = self.kv.get(uc.encode("utf-8"))
        if u:
            courses = u.courses.values()
            courses.sort(key=lambda x: x["term"], reverse=True)
            self.render("admin_user.html", user=u, courses=courses)
        else:
            raise tornado.web.HTTPError(404)
    
    @authenticated
    def post(self):
        pass

class GroupMessage(AdminHandler):
    @authenticated
    def get(self):
        pass
    
    @authenticated
    def post(self):
        tolist = self.get_arguments("to")
        msg = self.get_argument("msg")
        for uc in tolist:
            u = self.kv.get(uc.encode("utf-8"))
            noteinfo = {
                    "n": u.mobileno,
                    "p": u.mobilepass,
                    "c": (u"Hello，%s！%s。[Noven]" % (u.name, msg)).encode("utf-8")
                }
            sae.taskqueue.add_task("send_notification_sms_task", "/backend/sms", urllib.urlencode(noteinfo))
            print "%s - SMS pushed into taskqueue." % u.mobileno
