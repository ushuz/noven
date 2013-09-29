# -*- coding:utf-8 -*-

import os
import base64
import functools
import hashlib
import logging

import sae
import sae.kvdb
import sae.taskqueue
import tornado.web
import tornado.template

from tornado.escape import utf8, _unicode

# Import the main libs for the app.
from libs import alpha
from libs import beta
from libs import NovenFetion
from libs import NovenWx


# ----------------------------------------------------------------------
# Useful little helpers


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


def create_signature(msg):
    secret = "IAmACoward"
    if not msg:
        return None
    return hashlib.sha1(secret+utf8(msg)).hexdigest()


def create_message(tpl, **kw):
    t = tornado.template.Template(tpl)
    return _unicode(t.generate(**kw))


# ----------------------------------------------------------------------
# Base handlers

class BaseHandler(tornado.web.RequestHandler):
    def initialize(self, *args, **kwargs):
        self.kv = sae.kvdb.KVClient()

    def get_current_user(self):
        try:
            return self.kv.get(self.get_secure_cookie("uc"))
        except:
            pass

    def write_error(self, status_code, **kwargs):
        if status_code == 404:
            error = "您要的东西不在这儿。"
            self.render("sorry.html", error=error)
        elif status_code >= 500:
            error = "服务器开小差了。"
            self.render("sorry.html", error=error)


class ErrorHandler(BaseHandler):
    def initialize(self, status_code):
        self.set_status(status_code)

    def prepare(self):
        raise tornado.web.HTTPError(self._status_code)

    def check_xsrf_cookie(self):
        # POSTs to an ErrorHandler don't actually have side effects,
        # so we don't need to check the XSRF token.  This allows POSTs
        # to the wrong URL to return a 404 instead of 403.
        pass

# Override default error handler to display customized error pages.
tornado.web.ErrorHandler = ErrorHandler


# ----------------------------------------------------------------------
# Main handlers


class SignupHandler(BaseHandler):
    def get(self):
        t = self.get_argument("t", None)
        s = self.get_argument("s", None)
        total = self.kv.get_info()["total_count"]
        self.render("signup.html", total=total, t=t, s=s)

    def post(self):
        t = self.get_argument("t", None)
        s = self.get_argument("s", None)
        ucode = self.get_argument("uc", None)
        upass = self.get_argument("up", None)
        mcode = self.get_argument("mc", None)
        mpass = self.get_argument("mp", None)

        # Check ucode at the very first.
        if ucode and ucode.isdigit():
            pass
        else:
            self.redirect("/sorry")
            return

        # Check token and signature.
        if create_signature(t) != s:
            # If failed on consistency, then fallback to fetion-only sign-up.
            # Under such condition, mcode is required.
            t = None
            if not mcode:
                self.redirect("/sorry")
                return

        # Check mobile.
        if mcode and len(mcode) != 11 and mcode.isdigit() and not mpass:
            self.redirect("/sorry")
            return

        try:
            # 9 digits for BJFU
            if len(ucode) == 9:
                new_user = alpha.User(
                    ucode, upass, mcode, mpass, t
                )
            # 10 digits for ZJU
            elif len(ucode) == 10:
                new_user = beta.User(
                    ucode, upass, mcode, mpass, t
                )
            # Invalid usercode
            else:
                raise Exception("Invalid usercode.")
        except Exception as e:
            logging.info("%s - Sign-up Failed: %s", ucode, e)
            self.redirect("/sorry")
            return

        self.set_secure_cookie("uc", ucode)

        TPL_VCODE = u'''Hello，%s！您的登记验证码：%s [Noven]'''
        if new_user.mobileno and new_user.mobilepass:
            # If user's usercode and password are OK, then we should send
            # verification SMS.  SMS should be sent synchronously in order to
            # redirect the user to error page when NovenFetion.AuthError occurs.
            n = new_user.mobileno.encode("utf-8")
            p = new_user.mobilepass.encode("utf-8")
            c = utf8(TPL_VCODE % (new_user.name,
                hashlib.sha1(self._new_cookie["uc"].value).hexdigest()[:6]))

            fetion = NovenFetion.Fetion(n, p)
            while True:
                try:
                    fetion.login()
                except NovenFetion.AuthError as e:
                    logging.info("%s - Sign-up Failed: %s", ucode, e)
                    self.redirect("/sorry")
                    return
                except Exception:
                    continue
                break
            fetion.send_sms(c)
            fetion.logout()

            # If SMS is sent, log and move on.
            logging.info("%s - SMS Sent: To %s.", ucode, n)

            # `set()` only takes str as key, WTF!
            # As a result, we have to encode the KEY cause it is unicode.
            self.kv.set(new_user.usercode.encode("utf-8"), new_user)
            self.redirect("/verify")
        elif new_user.wx_id:
            new_user.verified = True
            self.kv.set(utf8(new_user.usercode), new_user)
            self.redirect("/welcome")
        else:
            self.redirect("/sorry")


class VerifyHandler(BaseHandler):
    @authenticated
    def get(self):
        self.render("verify.html")

    @authenticated
    def post(self):
        vcode = self.get_argument("vcode", None)
        u = self.current_user

        if vcode.lower() == hashlib.sha1(self.get_cookie("uc")).hexdigest()[:6]:
            u.verified = True
            self.kv.set(utf8(u.usercode), u)
            self.redirect("/welcome")
        else:
            logging.info("%s - Sign-up Failed: Wrong verification code.", u.usercode)
            self.redirect("/sorry")


class WelcomeHandler(BaseHandler):
    @authenticated
    def get(self):
        u = self.current_user
        if u.verified:
            self.render("welcome.html")

            # Here `init()` could be async.
            try:
                u.init()
            except Exception as e:
                logging.error("%s - Init Failed: %s", u.usercode, e)
            self.kv.set(u.usercode.encode("utf-8"), u)

            if u.wx_id:
                self.kv.set(utf8(u.wx_id), utf8(u.usercode))

            if u.mobileno:
                wellinfo = utf8(create_message(u.TPL_WELCOME, u=u))
                wellinfo = base64.b64encode(wellinfo)
                sae.taskqueue.add_task(
                    "send_verify_sms_task",
                    "/backend/sms/%s" % u.usercode,
                    wellinfo
                )

            logging.info("%s - Sign-up Done.", u.usercode)
        else:
            self.redirect("/")


class SorryHandler(BaseHandler):
    def get(self):
        error = "请检查学号、教务系统密码、手机号码、飞信密码输入是否有误。<br/>" \
                "若您已不记得飞信密码，请编辑新密码发送到12520050重置您的飞信密码。"
        self.render("sorry.html", error = error)


class ReportHandler(BaseHandler):
    """Display users' reports."""
    def get(self):
        t = self.get_argument("t", None)
        s = self.get_argument("s", None)
        n = self.get_argument("n", None)
        
        # if create_signature(t) != s:
        #     self.redirect("/sorry")
        #     return

        uc = self.kv.get(utf8(t))
        u = self.kv.get(uc)

        self.render("report.html", u=u, school="北京林业大学")


# ----------------------------------------------------------------------
# Brand new TaskHandlers


class TaskHandler(tornado.web.RequestHandler):
    def initialize(self, *args, **kwargs):
        self.kv = sae.kvdb.KVClient()


class UpdateAll(TaskHandler):
    def get(self):
        # We make breakpoint a marker to continue the update process.
        # Depending on the type of the marker, only the matching group will be
        # pushed into queue.  That's to say, if marker is a ZJU id, `ucs` would
        # be empty, only ZJU users would be pushed into queue.
        marker = self.get_argument("marker", None)

        # ZJU update.
        ids = self.kv.getkeys_by_prefix("3", limit=1000, marker=marker)
        try:
            # If the for-loop breaks at its first element, id will not be created
            # and cause NameError when handling exception.
            id = ""
            for id in ids:
                sae.taskqueue.add_task("update_queue", "/backend/update/%s" % id)
        except sae.taskqueue.Error as e:
            logging.error("%s - Update Failed: To be continued.")
            sae.taskqueue.add_task("update_queue", "/backend/update?marker=%s" % id)

        # BJFU update.
        ucs = self.kv.getkeys_by_prefix("1", limit=1000, marker=marker)
        try:
            uc = ""
            for uc in ucs:
                sae.taskqueue.add_task("update_queue", "/backend/update/%s" % uc)
        except sae.taskqueue.Error as e:
            # KVDB is annoying.  We may encounter different errors, such as `Timed
            # Out`, `No Server Available`, etc.  We should just continue from here.
            logging.error("%s - Update Failed: To be continued.")
            sae.taskqueue.add_task("update_queue", "/backend/update?marker=%s" % uc)


class UpdateById(TaskHandler):
    def get(self, id):
        u = self.kv.get(id.encode("utf-8"))
        if not u:
            # Can't get user from KVDB.
            logging.error("%s - Update Failed: User not exists.", id)
            return
        if not u.verified:
            # User is not activated.
            logging.error("%s - Update Failed: User not activated.", id)
            return

        # Debug settings
        if "SERVER_SOFTWARE" not in os.environ:
            alpha.DATA_URL = "http://127.0.0.1:8888/data"
            beta.DATA_URL = "http://127.0.0.1:8888/xscj.aspx?xh=%s"

        try:
            new_courses = u.update()
        except (alpha.AuthError, beta.AuthError) as e:
            # User changed their password for sure. Deactivate them.
            u.verified = False
            self.kv.set(u.usercode.encode("utf-8"), u)
            logging.info("%s - Deactivated: User changed password.", id)
            logging.error("%s - Update Failed: %s", id, e)
            return
        except Exception as e:
            logging.error("%s - Update Failed: %s", id, e)
            return

        if new_courses:
            # If `u.wx_id` exists, we should update `u.wx_push` with `new_courses`
            # so that we can return it when users performs a score query by Weixin,
            # no matter `u.mobileno` exists or not.
            if u.wx_id:
                u.wx_push.update(new_courses)

            # If `u.mobileno` exists, we should notify the user via SMS.
            if u.mobileno:
                noteinfo = utf8(create_message(u.TPL_NEW_COURSES, u=u, new_courses=new_courses))
                noteinfo = base64.b64encode(noteinfo)
                sae.taskqueue.add_task(
                    "send_notification_sms_task",
                    "/backend/sms/%s" % u.usercode,
                    noteinfo
                )

        # Save to KVDB after every update.
        # Rank maybe updated without new releases,
        self.kv.set(u.usercode.encode("utf-8"), u)


class SMSById(TaskHandler):
    def post(self, id):
        u = self.kv.get(id.encode("utf-8"))
        if not u:
            # Can't get user from KVDB.
            logging.error("%s - SMS Failed: User not exists.", id)
            return
        if not u.verified:
            # User is not verified.
            logging.error("%s - SMS Failed: User not activated.", id)
            return

        n = u.mobileno.encode("utf-8")  # Mobile number
        p = u.mobilepass.encode("utf-8")  # Fetion password
        c = base64.b64decode(self.request.body) + "[Noven]"  # SMS content

        fetion = NovenFetion.Fetion(n, p)
        while True:
            try:
                fetion.login()
            except NovenFetion.AuthError as e:
                logging.error("%s - SMS Failed: %s", id, e)
                # `NovenFetion.AuthError` means users had changed Fetion password
                # for sure.  Deactivate them.
                u.verified = False
                self.kv.set(id.encode("utf-8"), u)
                logging.info("%s - Deactivated: User changed Fetion password.", id)
                return
            except Exception:
                continue
            break
        fetion.send_sms(c)
        fetion.logout()

        logging.info("%s - SMS Sent to %s.", id, n)

    def check_xsrf_cookie(self):
        pass


# ----------------------------------------------------------------------
# Brand new WxHandler


class WxHandler(TaskHandler):
    def get(self):
        s = self.get_argument("echostr", None)
        if s:
            self.write(s.encode("utf-8"))
            return
        self.render("weixin.html")

    def post(self):
        msg = self.msg = NovenWx.parse(self.request.body)

        print msg.fr+" "+str(type(msg))

        if isinstance(msg, NovenWx.BlahMessage):
            self.reply(u"收到！")
            return

        # Check user's existence so we WON'T need to check it in every logic.
        # If user doesn't exist, reply the guide.
        uc = self.kv.get(msg.fr.encode("utf-8"))
        if not uc:
            self.reply("guide")
            return

        u = self.kv.get(uc)
        if not u:
            self.reply("guide")
            return

        # Score query logic.
        # Score query supposes to be the most frequent action when noven goes
        # online.  Score query logic goes first in order to save IF computes.
        if isinstance(msg, NovenWx.QueryMessage):
            if u.wx_push:
                # TPL_NEW_COURSES
                self.reply(create_message(u.TPL_NEW_COURSES, u=u, new_courses=u.wx_push))
                u.wx_push = {}
                self.kv.set(u.usercode.encode("utf-8"), u)
                return
            else:
                # TPL_NO_UPDATE
                self.reply(create_message(u.TPL_NO_UPDATE, u=u))
                return

        # Menu
        # User is requesting menu.
        if isinstance(msg, NovenWx.MenuMessage):
            self.reply("menu")
            return

        # Subscribe event.
        # Check whether the user exists.  If exists, activate the user and
        # welcome back.  Otherwise, it's a new follower, return the guide.
        if isinstance(msg, NovenWx.HelloMessage):
            u.verified = True
            self.kv.set(uc, u)
            logging.info("%s - Activated: Re-Subsciribe.", uc)
            self.reply(u"Hello，%s！欢迎回来！" % u.name)
            return

        # Unsubscribe event.
        # Deactivate users when they unsubscribe to save unnecessary update.
        # In case of users' returning back, we don't delete data.
        if isinstance(msg, NovenWx.ByeMessage):
            u.verified = False
            self.kv.set(uc, u)
            logging.info("%s - Deactivated: Unsubscribe.", uc)
            return
        else:
            # Handle unknown message here.
            pass

    def check_xsrf_cookie(self):
        # POSTs are made by Tencent servers, so XSRF COOKIE doesn't exist.
        # Checking XSRF COOKIE becomes unnecessary under such condition.
        # While Weixin has offered a way to authenticate the POSTs, which
        # can be implemented here later if it is needed.
        pass

    def reply(self, content):
        msg = self.msg
        if content == "guide":
            self.render("guide.xml", to=msg, t=msg.fr, s=create_signature(msg.fr))
        elif content == "menu":
            self.render("menu.xml", to=msg)
        else:
            self.render("text.xml", to=msg, content=content)
