# -*- coding:utf-8 -*-

import urllib
import hashlib
import functools
import logging
import base64

import sae
import sae.kvdb
import sae.taskqueue
import tornado.web

from tornado.escape import utf8, _unicode

# Import the main libs for the app.
from libs import alpha2 as alpha
from libs import NovenFetion
from libs import NovenWx


NEW_COURSES_TPL = u'''Hello，%s！有%d门课出分了：%s。当前学期您的学分积为%s，全学程您的学分积为%s，%s。'''
VCODE_MESSAGE_TPL = u'''Hello，%s！您的登记验证码：%s '''
WELCOME_MESSAGE_TPL = u'''Hello，%s！全学程您的学分积为%s，%s，共修过%d门课。加油！'''


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


# Main handlers
class SignupHandler(BaseHandler):
    def get(self):
        token = self.get_argument("t", None)
        signed = self.get_argument("s", None)
        self.render("signup.html", total=self.kv.get_info()["total_count"], t=token, s=signed)

    def post(self):
        ucode = self.get_argument("uc", None)
        upass = self.get_argument("up", None)
        mcode = self.get_argument("mc", None)
        mpass = self.get_argument("mp", None)

        self.set_secure_cookie("uc", ucode)
        try:
            new_user = alpha.User(
                ucode, upass, mcode, mpass
            )
        except alpha.AuthError as e:
            logging.info("%s - Sign-up Failed: %s.", ucode, e)
            self.redirect("/sorry")
            return

        if new_user.name:
            # If user's usercode and password are OK, then we should send
            # verification SMS.  SMS should be sent synchronously in order to
            # redirect the user to error page when AuthError occurs.
            n = new_user.mobileno.encode("utf-8")
            p = new_user.mobilepass.encode("utf-8")
            c = (VCODE_MESSAGE_TPL % (new_user.name, hashlib.sha1(self._new_cookie["uc"].value).hexdigest()[:6])).encode("utf-8")

            fetion = NovenFetion.Fetion(n, p)
            while True:
                try:
                    fetion.login()
                    fetion.send_sms(c)
                    fetion.logout()
                except NovenFetion.AuthError as e:
                    logging.info("%s - Sign-up Failed: %s.", ucode, e)
                    self.redirect("/sorry")
                    return
                except Exception:
                    continue
                break
            # If SMS is sent, log and move on.
            logging.info("%s - SMS Sent: To %s.", ucode, n)

            # `set()` only takes str as key, WTF!
            # As a result, we have to encode the KEY 'cause it is unicode.'
            self.kv.set(new_user.usercode.encode("utf-8"), new_user)
            self.redirect("/verify")
        else:
            self.redirect("/sorry")


class VerifyHandler(BaseHandler):
    @authenticated
    def get(self):
        self.render("verify.html")

    def post(self):
        vcode = self.get_argument("vcode", None)

        if vcode.lower() == hashlib.sha1(self.get_cookie("uc")).hexdigest()[:6]:
            self.current_user.verified = True
            self.kv.set(self.current_user.usercode.encode("utf-8"), self.current_user)
            self.redirect("/welcome")
        else:
            logging.info("%s - Sign-up Failed: Wrong verification code.")
            self.redirect("/sorry")


class WelcomeHandler(BaseHandler):
    @authenticated
    def get(self):
        if self.current_user.verified:
            self.render("welcome.html")

            u = self.current_user
            # Here `init()` could be async.
            u.init()
            self.kv.set(u.usercode.encode("utf-8"), u)
            logging.info("%s - Sign-up Done.")

            wellinfo = (WELCOME_MESSAGE_TPL % (u.name, u.GPA, u.rank, len(u.courses))).encode("utf-8")
            wellinfo = base64.b64encode(wellinfo)
            sae.taskqueue.add_task("send_verify_sms_task", "/backend/sms/%s" % u.usercode, wellinfo)
        else:
            self.redirect("/")


class SorryHandler(BaseHandler):
    def get(self):
        error = "请检查学号、密码、手机号、飞信密码及验证码是否输入有误。<br/>" \
                "若您已不记得飞信密码，可以编辑新密码发送到12520050重置您的飞信密码。"
        self.render("sorry.html", error = error)


# ----------------------------------------------------------------------
# Brand new TaskHandlers


class TaskHandler(tornado.web.RequestHandler):
    def initialize(self, *args, **kwargs):
        self.kv = sae.kvdb.KVClient()


class UpdateAll(TaskHandler):
    def get(self):
        marker = self.get_argument("marker", None)
        # The users base is very large right now, so we have to change the prefix.
        ucs = self.kv.getkeys_by_prefix("1", limit=1000, marker=marker)
        for uc in ucs:
            sae.taskqueue.add_task("update_queue", "/backend/update/%s" % uc)


class UpdateById(TaskHandler):
    def get(self, id):
        u = self.kv.get(id.encode("utf-8"))
        if not u:
            # Can't get user from KVDB.
            logging.error("%s - Update Failed: User not exists.", id)
            return
        if not u.verified:
            # User is not verified.
            logging.error("%s - Update Failed: User not activated.", id)
            return

        alpha.DATA_URL = "http://127.0.0.1:8888/data"
        try:
            new_courses = u.update()
        except alpha.AuthError as e:
            # User changed their password for sure. Deactivate them.
            logging.error("%s - Update Failed: %s.", id, e)
            u.verified = False
            self.kv.set(u.usercode.encode("utf-8"), u)
            logging.info("%s - Deactivated: User changed password.", id)
            return

        if new_courses:
            # If `u.wx_id` exists, SMS should not be sent.  Instead, we
            # update `u.wx_push` with `new_courses` so that we can return
            # it when users performs a score query by Weixin.
            if u.wx_id:
                u.wx_push.update(new_courses)
                self.kv.set(u.usercode.encode("utf-8"), u)
                return

            self.kv.set(u.usercode.encode("utf-8"), u)
            tosend = u"、".join([u"%s(%s)" % (v.subject, v.score) for v in new_courses.values()])

            noteinfo = (NEW_COURSES_TPL % (u.name, len(new_courses), tosend,
                u.current_GPA, u.GPA, u.rank)).encode("utf-8")
            noteinfo = base64.b64encode(noteinfo)
            sae.taskqueue.add_task("send_notification_sms_task", "/backend/sms/%s" % u.usercode, noteinfo)


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
        if u.wx_id:
            # Can't send SMS.
            logging.error("%s - SMS Failed: User using Weixin.")
            return

        n = u.mobileno.encode("utf-8")  # Mobile number
        p = u.mobilepass.encode("utf-8")  # Fetion password
        c = base64.b64decode(self.request.body) + "[Noven]"  # SMS content

        fetion = NovenFetion.Fetion(n, p)
        while True:
            try:
                fetion.login()
                fetion.send_sms(c)
                fetion.logout()
            except NovenFetion.AuthError as e:
                logging.error("%s - SMS Failed: Wrong password for %s.", id, n)
                # `NovenFetion.AuthError` means users had changed Fetion password
                # for sure. Deactivate them.
                u.verified = False
                self.kv.set(id.encode("utf-8"), u)
                logging.info("%s - Deactivated: User changed Fetion password.", id)
                return
            except Exception:
                continue
            break
        logging.info("%s - SMS Sent to %s.", id, n)

    def check_xsrf_cookie(self):
        pass


class TempHandler(TaskHandler):
    def get(self):
        pass


WX_SIGNUP_FAIL = u'''Sorry，登记失败了！请检查学号、密码是否输入有误。'''
WX_SIGNUP_SUCC = u'''Hello，%s！全学程您的学分积为%s，%s，共修过%d门课。加油！'''
WX_GUIDE = u"\r\n".join([u"欢迎通过微信使用Noven！",
                         u"Noven可以帮助你查询最近出分状况，省去了频繁登录教务系统的烦恼~",
                         u"",
                         u"微信公众号是为无法使用飞信的同学而特别准备的。若您是飞信用户，"
                         u"欢迎到Noven网站登记：noven.sinaapp.com，如有新课程出分将自动短信通知，比微信更方便快捷~",
                         u"",
                         u"登记：发送“ZC 学号 教务系统密码”（请用空格隔开，不包括引号）",
                         u"查询：登记后发送任意内容即可查询最近出分状况",
                         u"",
                         u"若您已在网站登记，微信登记后短信通知将随即终止"])
WX_NO_UPDATE = u'''Hello，%s！最近没有新课程出分。当前学期您的学分积为%s，全学程您的学分积为%s，%s。'''
WX_NEW_RELEASE = u'''Hello，%s！有%d门课出分了：%s。当前学期您的学分积为%s，全学程您的学分积为%s，%s。'''
WX_NOT_SIGNED = u'''Sorry，您尚未登记！请发送“ZC 学号 密码”（请用空格隔开，不包括引号）进行登记。'''


class WxHandler(TaskHandler):
    def get(self):
        s = self.get_argument("echostr", None)
        if s:
            self.write(s.encode("utf-8"))
            return
        self.render("weixin.html")

    def post(self):
        msg = NovenWx.parse(self.request.body)

        print msg.fr

        # Score query logic.
        # Score query supposes to be the most frequent action when noven goes
        # online.  Score query logic goes first in order to save IF computes.
        if isinstance(msg, NovenWx.QueryMessage):
            uc = self.kv.get(msg.fr.encode("utf-8"))
            if uc:
                u = self.kv.get(uc)
                if u.wx_push:
                    tosend = u"、".join([u"%s(%s)" % (v.subject, v.score) for v in u.wx_push.values()])
                    self.reply(msg, WX_NEW_RELEASE % (u.name, len(u.wx_push), tosend, u.current_GPA, u.GPA, u.rank))
                    u.wx_push = {}
                    self.kv.set(u.usercode.encode("utf-8"), u)
                    return
                else:
                    self.reply(msg, WX_NO_UPDATE % (u.name, u.current_GPA, u.GPA, u.rank))
                    return
            else:
                self.reply(msg, WX_NOT_SIGNED)
                return

        # Subscribe event.
        # Check whether the user exists. If exists, activate the user and
        # return `SUCC`. Otherwise, it's a new follower, return the guide.
        if isinstance(msg, NovenWx.HelloMessage):
            uc = self.kv.get(msg.fr.encode("utf-8"))
            if uc:
                u = self.kv.get(uc)
                if u.wx_id:
                    u.verified = True
                    self.kv.set(uc, u)
                    logging.info("%s - Activated: Re-Subsciribe.", uc)
                    self.reply(msg, u"Hello，%s！欢迎回来！" % u.name)
                    return
            self.reply(msg, WX_GUIDE)
            return

        # Unsubscribe event.
        # Deactivate users when they unsubscribe to save unnecessary update.
        # In case of users' returning back, we don't delete data.
        if isinstance(msg, NovenWx.ByeMessage):
            uc = self.kv.get(msg.fr.encode("utf-8"))
            if uc:
                u = self.kv.get(uc)
                if u.wx_id:
                    u.verified = False
                    self.kv.set(uc, u)
                    logging.info("%s - Deactivated: Unsubscribe.", uc)
                    return

        # Sign up logic.
        if isinstance(msg, NovenWx.SignupMessage):
            if self.kv.get(msg.fr.encode("utf-8")):
                self.reply(msg, u"Hello，您已成功登记！回复任意内容查询最近出分状况。")
                return
            u = self.kv.get(msg.usercode.encode("utf-8"))

            if u and u.password == msg.password:
                u.wx_id = msg.fr
                u.verified = True
                u.mobileno = None
                u.mobilepass = None
            else:
                u = alpha.User(
                    ucode = msg.usercode,
                    upass = msg.password,
                    wid   = msg.fr
                )
                if u.name:
                    u.verified = True
                    # `u.init()` takes time to finish, and it is likely
                    # to exceed 5s time limit for a Weixin reply.  I can't
                    # find a solution right now, may there will be one later.
                    u.init()

            if u.verified:
                # `set()` only takes str as key, WTF!
                self.kv.set(u.usercode.encode("utf-8"), u)
                self.kv.set(msg.fr.encode("utf-8"), u.usercode.encode("utf-8"))
                self.reply(msg, WX_SIGNUP_SUCC % (u.name, u.GPA, u.rank, len(u.courses)))
                return
            else:
                self.reply(msg, WX_SIGNUP_FAIL)
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

    def reply(self, received, content):
        self.write(NovenWx.reply(received, content))
