# -*- coding:utf-8 -*-

import base64
import functools
import hashlib
import logging
import os
import time

import sae
import sae.kvdb
import sae.taskqueue
import tornado.web
import tornado.template

from tornado.escape import utf8, _unicode

# Import the main libs for the app.
from libs import alpha2 as alpha
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
            raise tornado.web.HTTPError(424)
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

    def write_error(self, status_code, **kwargs):
        errors = {
            # 401 for token expired
            401: "链接已失效，请重新获取。",

            # 404 for non-existence resources
            404: "您要的东西不在这儿。",

            # 421 for wrong usercode or password
            421: "学号或教务系统密码有误。",

            # 422 for wrong mobile or password
            422: "手机号码或飞信密码有误。<br />" \
                "若忘记飞信密码，请编辑新密码发送到12520050即可。",

            # 423 for non-CMCC mobile
            423: "仅支持中国移动号码。",

            # 425 for activation
            425: "验证码有误。",

            # 426 for duplicate sign-up
        }

        # 5XX for server
        if status_code >= 500:
            error = "服务器开小差了，去找 Noven 打个小报告吧！"
        else:
            error = errors.get(status_code, "请联系 Noven 。")

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


# Override default error handler to display customized error pages for
# un-mapped urls.
tornado.web.ErrorHandler = ErrorHandler


class SignUpHandler(BaseHandler):
    def prepare(self):
        self.log = logging.getLogger("Noven.SignUp")

    def get_current_user(self):
        try:
            return self.kv.get(self.get_secure_cookie("uc"))
        except:
            pass


class TaskHandler(tornado.web.RequestHandler):
    def initialize(self, *args, **kwargs):
        self.kv = sae.kvdb.KVClient()


# ----------------------------------------------------------------------
# Main handlers


class HomeHandler(SignUpHandler):
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

        self.log.info("%s - Token: %s Mobile: %s", ucode, t, mcode)

        # Check ucode at the very first.
        if not ucode or not ucode.isdigit():
            self.log.error("%s - Invalid usercode.", ucode)
            raise tornado.web.HTTPError(421)

        # Check token and signature.
        if create_signature(t) != s:
            # If failed on consistency, raise, no fallback.
            self.log.error("%s - Invalid token: %s.", ucode, t)
            raise tornado.web.HTTPError(424)

        # Check mobile.
        if mcode and (len(mcode) != 11 or not mcode.isdigit() or not mpass):
            self.log.error("%s - Invalid mobile: %s.", ucode, mcode)
            raise tornado.web.HTTPError(422)

        # TODO: Check carrier

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
            self.log.error("%s - %s", ucode, e)
            raise tornado.web.HTTPError(421)

        self.log.info("%s - User created.", ucode)
        self.set_secure_cookie("uc", ucode)

        TPL_VCODE = u'''Hello，%s！您的登记验证码：%s [Noven]'''
        if new_user.mobileno and new_user.mobilepass:
            # If user's usercode and password are OK, then we should send
            # activation SMS.  SMS should be sent synchronously in order to
            # redirect the user to error page when NovenFetion.AuthError occurs.
            n = utf8(new_user.mobileno)
            p = utf8(new_user.mobilepass)
            c = utf8(TPL_VCODE % (new_user.name,
                    hashlib.sha1(self._new_cookie["uc"].value).hexdigest()[:6]))

            fetion = NovenFetion.Fetion(n, p)
            while True:
                try:
                    fetion.login()
                    fetion.send_sms(c)
                    fetion.logout()
                except NovenFetion.AuthError as e:
                    self.log.error("%s - %s", ucode, e)
                    raise tornado.web.HTTPError(422)
                except Exception:
                    continue
                break

            # If SMS is sent, log and move on.
            self.log.info("%s - Activation code sent to %s.", ucode, n)

            # `set()` only takes str as key, WTF!
            # As a result, we have to encode the KEY cause it is unicode.
            self.kv.set(utf8(new_user.usercode), new_user)
            self.redirect("/verify")
        elif new_user.wx_id:
            new_user.verified = True
            self.kv.set(utf8(new_user.usercode), new_user)
            self.log.info("%s - Activated.", ucode)
            self.redirect("/welcome")
        else:
            self.log.critical("%s - Invalid User Object.", ucode, e)
            raise tornado.web.HTTPError(424)


class VerifyHandler(SignUpHandler):
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
            self.log.info("%s - Activated.", u.usercode)
            self.redirect("/welcome")
        else:
            self.log.error("%s - Wrong Activation code.", u.usercode)
            raise tornado.web.HTTPError(425)


class WelcomeHandler(SignUpHandler):
    @authenticated
    def get(self):
        u = self.current_user
        if u.verified:
            self.render("welcome.html")

            # Here `init()` could be async.
            try:
                u.init()
            except Exception as e:
                self.log.critical("%s - %s", u.usercode, e)
            self.kv.set(utf8(u.usercode), u)

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

            self.log.info("%s - Name: %s Courses: %d",
                u.usercode, u.name, len(u.courses))
        else:
            self.redirect("/")


class ReportHandler(BaseHandler):
    """Display users' reports."""
    def get(self):
        t = self.get_argument("t", None)
        s = self.get_argument("s", None)
        n = self.get_argument("n", None)

        # Get logger before logging.
        log = logging.getLogger("Noven.Report")

        # Authenticate the user.
        # Turn down illegal accesses by 424.  If shit happened to normal
        # users, 424 can guide them to contact Noven.
        if not t or not s or not n or create_signature(t[:20]+n[-8:]) != s:
            log.error("%s - Illegal access.", t)
            raise tornado.web.HTTPError(424)

        # Session expires in 24 hours.
        # Tell users their Token expired by 401.
        if time.time() - float(n) > 3600 * 24:
            log.error("%s - Token expired.", t)
            raise tornado.web.HTTPError(401)

        uc = self.kv.get(utf8(t))
        # Check if usercode was successfully retrieved.
        if not uc:
            log.critical("%s - Failed to retrieve usercode.", t)
            raise tornado.web.HTTPError(424)

        u = self.kv.get(uc)
        # Check if User object was successfully retrieved.
        if not u:
            log.critical("%s - Failed to retrieve user.", uc)
            raise tornado.web.HTTPError(424)


        u.terms = sorted(list(set([c.term for c in u.courses.values()])), reverse=True)
        self.render("report.html", u=u)
        log.info("%s - %s's report accessed.", uc, u.name)


# ----------------------------------------------------------------------
# Brand new WxHandler


class WxHandler(TaskHandler):
    def get(self):
        s = self.get_argument("echostr", None)
        if s:
            self.write(utf8(s))
            return
        self.render("weixin.html")

    def post(self):
        msg = self.msg = NovenWx.parse(self.request.body)

        log = logging.getLogger("Noven.Weixin")

        # print msg.fr+" "+str(type(msg))
        log.info("%s %s", msg.fr, str(type(msg)))

        if isinstance(msg, NovenWx.BlahMessage):
            if msg.content[1:] == u"成绩单":
                self.render("menu-with-report.xml", to=msg, create_signature=create_signature)
                return
            self.reply(u"收到！")
            return

        # Check user's existence so we WON'T need to check it in every logic.
        # If user doesn't exist, reply the guide.
        uc = self.kv.get(utf8(msg.fr))
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
                self.kv.set(utf8(u.usercode), u)
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

        # Subscribe event from an exist user.
        # Activate the user and welcome back.
        if isinstance(msg, NovenWx.HelloMessage):
            u.verified = True
            self.kv.set(uc, u)
            log.info("%s - Activated.", uc)
            self.reply(u"Hello，%s！欢迎回来！" % u.name)
            return

        # Unsubscribe event.
        # Deactivate users when they unsubscribe to save unnecessary update.
        # In case of users' returning back, we don't delete data.
        if isinstance(msg, NovenWx.ByeMessage):
            u.verified = False
            self.kv.set(uc, u)
            log.info("%s - De-Activated: Un-Subscribe.", uc)
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
            self.render("guide.xml", to=msg, create_signature=create_signature)
        elif content == "menu":
            self.render("menu.xml", to=msg, create_signature=create_signature)
        else:
            self.render("text.xml", to=msg, content=content)


# ----------------------------------------------------------------------
# Brand new TaskHandlers


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
            sae.taskqueue.add_task("update_queue", "/backend/update?marker=%s" % uc)


class UpdateById(TaskHandler):
    def get(self, id):
        log = logging.getLogger("Noven.Update")

        u = self.kv.get(utf8(id))
        if not u:
            # Can't get user from KVDB.
            log.error("%s - User not exists.", id)
            return
        if not u.verified:
            # User is not activated.
            # log.error("%s - User not activated.", id)
            return

        # Debug settings
        if "SERVER_SOFTWARE" not in os.environ:
            alpha.DATA_URL = "http://127.0.0.1:8888/data"
            beta.DATA_URL = "http://127.0.0.1:8888/xscj.aspx?xh=%s"

        try:
            new_courses = u.update()
        except (alpha.AuthError, beta.AuthError) as e:
            log.error("%s - %s", id, e)
            # User changed their password for sure. Deactivate them.
            u.verified = False
            self.kv.set(utf8(u.usercode), u)
            log.info("%s - De-Activated: User changed password.", id)
            return
        except Exception as e:
            log.error("%s - %s", id, e)
            return

        if new_courses:
            log.info("%s - %s has %s updates. GPA %s.", id, u.name, len(new_courses), u.GPA)

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
        self.kv.set(utf8(u.usercode), u)


class SMSById(TaskHandler):
    def post(self, id):
        log = logging.getLogger("Noven.SMS")

        u = self.kv.get(utf8(id))
        if not u:
            # Can't get user from KVDB.
            log.error("%s - User not exists.", id)
            return
        # if not u.verified:
            # User is not verified.
            # log.error("%s - SMS Failed: User not activated.", id)
            # return

        n = utf8(u.mobileno)  # Mobile number
        p = utf8(u.mobilepass)  # Fetion password
        c = base64.b64decode(self.request.body) + "[Noven]"  # SMS content

        fetion = NovenFetion.Fetion(n, p)
        while True:
            try:
                fetion.login()
                fetion.send_sms(c)
                fetion.logout()
            except NovenFetion.AuthError as e:
                log.error("%s - %s", id, e)
                # Users had changed Fetion password.  Deactivate them.
                u.verified = False
                self.kv.set(utf8(id), u)
                log.info("%s - De-Activated: User changed Fetion password.", id)
                return
            except Exception:
                continue
            break

        log.info("%s - SMS Sent to %s.", id, n)

    def check_xsrf_cookie(self):
        pass
