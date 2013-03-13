# -*- coding:utf-8 -*-

import urllib
import hashlib
import functools

import sae
import sae.kvdb
import sae.taskqueue
import tornado.web

# Import the main libs for the app.
from libs import alpha2 as alpha
from libs import NovenFetion
from libs import NovenWx


NEW_COURSES_TPL = u'''Hello，%s！有%d门课出分了：%s。当前学期您的学分积为%s，全学程您的学分积为%s，%s。[Noven]'''
VCODE_MESSAGE_TPL = u'''Hello，%s！您的登记验证码：%s [Noven]'''
WELCOME_MESSAGE_TPL = u'''Hello，%s！全学程您的学分积为%s，%s，共修过%d门课。加油！[Noven]'''


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


# Override default error handler to display costumized error pages.
class ErrorHandler(BaseHandler):
    def initialize(self, status_code):
        self.set_status(status_code)

    def prepare(self):
        raise tornado.web.HTTPError(self._status_code)

    def check_xsrf_cookie(self):
        # POSTs to an ErrorHandler don't actually have side effects,
        # so we don't need to check the xsrf token.  This allows POSTs
        # to the wrong url to return a 404 instead of 403.
        pass

tornado.web.ErrorHandler = ErrorHandler


# Main handlers
class SignupHandler(BaseHandler):
    def get(self):
        self.render("signup.html", total=self.kv.get_info()["total_count"])

    def post(self):
        userinfo = {
            "ucode": self.get_argument("uc", None),
            "upass": self.get_argument("up", None),
            "mcode": self.get_argument("mc", None),
            "mpass": self.get_argument("mp", None)
        }
        self.set_secure_cookie("uc", userinfo["ucode"])
        new_user = alpha.User(
            userinfo["ucode"],
            userinfo["upass"],
            userinfo["mcode"],
            userinfo["mpass"]
        )
        if new_user.name:
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
        veryinfo = {
            "n": self.current_user.mobileno,
            "p": self.current_user.mobilepass,
            "c": (VCODE_MESSAGE_TPL % (self.current_user.name, hashlib.sha1(self.get_cookie("uc")).hexdigest()[:6])).encode("utf-8")
        }
        sae.taskqueue.add_task("send_verify_sms_task", "/backend/sms", urllib.urlencode(veryinfo))

    def post(self):
        vcode = self.get_argument("vcode", None)

        if vcode.lower() == hashlib.sha1(self.get_cookie("uc")).hexdigest()[:6]:
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

            u = self.current_user
            u.init_data()
            self.kv.set(u.usercode.encode("utf-8"), u)
            wellinfo = {
                "n": self.current_user.mobileno,
                "p": self.current_user.mobilepass,
                "c": (WELCOME_MESSAGE_TPL % (u.name, u.GPA, u.rank, len(u.courses))).encode("utf-8")
            }
            sae.taskqueue.add_task("send_verify_sms_task", "/backend/sms", urllib.urlencode(wellinfo))
        else:
            self.redirect("/")


class SorryHandler(BaseHandler):
    def get(self):
        error = "请检查学号、密码、手机号、飞信密码及验证码是否输入有误。"
        self.render("sorry.html", error = error)


# Task handlers
class UpdateTaskHandler(BaseHandler):
    def get(self):
        # As `getkeys_by_prefix()` has a default max return limit(100), remember
        # to update limit when our user amount gets too large. 
        uclist = [uc for uc in self.kv.getkeys_by_prefix("") if len(uc) == 9]
        for uc in uclist:
            payload = {
                "uc": uc
            }
            sae.taskqueue.add_task("update_queue", "/backend/update", urllib.urlencode(payload))

    def post(self):
        uc = self.get_argument("uc", None)
        if not uc:
            print "Update Error: can't get argument `uc`."
            return
        
        u = self.kv.get(uc.encode("utf-8"))
        if not u or not u.verified or not u.name:
            print "Update Error: can't get `u` from KVDB."
            return

        alpha.DATA_URL = "http://127.0.0.1:8888/data"
        new_courses = u.update()

        if new_courses:
            # If `u.wx_id` exists, sms should not be sent.  Instead, we
            # update `u.wx_push` with `new_courses` so that we can return
            # it when users performs a score query by Weixin.
            if u.wx_id:
                u.wx_push.update(new_courses)
                self.kv.set(u.usercode.encode("utf-8"), u)
                return

            self.kv.set(u.usercode.encode("utf-8"), u)
            tosend = u"、".join([u"%s(%s)" % (v.subject, v.score) for v in new_courses.values()])

            noteinfo = {
                "n": u.mobileno,
                "p": u.mobilepass,
                "c": (NEW_COURSES_TPL % (u.name, len(new_courses), tosend, u.current_GPA, u.GPA, u.rank)).encode("utf-8")
            }
            sae.taskqueue.add_task("send_notification_sms_task", "/backend/sms", urllib.urlencode(noteinfo))
    
    def check_xsrf_cookie(self):
        # Taskqueue will POST to this url.  There is no need to check XSRF
        # in this case as the only argument is `uc` which is used to get a
        # user in KVDB and won't cause any trouble.
        pass


class SMSTaskHandler(BaseHandler):
    def post(self):
        n = self.get_argument("n").encode("utf-8")  # Mobile number
        p = self.get_argument("p").encode("utf-8")  # Fetion password
        c = self.get_argument("c").encode("utf-8")  # SMS content

        fetion = NovenFetion.Fetion(n, p)
        while True:
            try:
                fetion.login()
                fetion.send_sms(c)
                fetion.logout()
            except NovenFetion.AuthError, e:
                print str(e)
                return
            except Exception, e:
                print str(e)
                continue
            break

        print "%s - SMS sent" % n

    get = post

    def check_xsrf_cookie(self):
        pass


class UpgradeHandler(BaseHandler):
    def get(self):
        userlist = [ut[1] for ut in self.kv.get_by_prefix("") if isinstance(ut[1], alpha.User)]
        for user in userlist:
            u = alpha.User(user.usercode, user.password, user.mobileno, user.mobilepass)
            u.name, u.GPA, u.rank, u.verified = user.name, user.GPA, user.rank, user.verified
            u.init_data()
            self.kv.set(u.usercode.encode("utf-8"), u)
            self.write(u"<p>%s upgraded</p>" % u.usercode)


WX_SIGNUP_FAIL = u'''Sorry，登记失败了！请检查学号、密码是否输入有误。'''
WX_SIGNUP_SUCC = u'''Hello，%s！全学程您的学分积为%s，%s，共修过%d门课。加油！'''
WX_GUIDE = u"\r\n".join([u"欢迎通过微信使用Noven！",
                         u"登记：发送“ZC 学号 密码”（请用空格隔开，不包括引号）",
                         u"查询：登记后发送任意内容即可查询最近出分状况",
                         u"若您已在网站登记，微信登记后短信通知将随即终止"])
WX_NO_UPDATE = u'''Hello，%s！最近没有新课程出分。当前学期您的学分积为%s，全学程您的学分积为%s，%s。'''
WX_NEW_RELEASE = u'''Hello，%s！有%d门课出分了：%s。当前学期您的学分积为%s，全学程您的学分积为%s，%s。'''
WX_NOT_SIGNED = u'''Sorry，您尚未登记！请发送“ZC 学号 密码”（请用空格隔开，不包括引号）进行登记。'''


class WxHandler(BaseHandler):
    def get(self):
        s = self.get_argument("echostr", None)
        if s:
            self.write(s.encode("utf-8"))
            return
        self.render("weixin.html")

    def post(self):
        msg = NovenWx.parse(self.request.body)

        # print type(msg)

        # Score query logic.
        # Score query supposes to be the most frequent action when noven goes
        # online.  Score query logic goes first in order to save IF compute.
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

        # A new follower, return the guide.
        if isinstance(msg, NovenWx.HelloMessage):
            self.reply(msg, WX_GUIDE)
            return

        # Sign up logic.
        if isinstance(msg, NovenWx.SignupMessage):
            u = self.kv.get(msg.usercode.encode("utf-8"))

            if u and u.password == msg.password:
                u.wx_id = msg.fr
                u.verified = True
            else:
                u = alpha.User(
                    ucode = msg.usercode,
                    upass = msg.password,
                    wid   = msg.fr
                )
                if u.name:
                    u.verified = True
                    # `u.init_data()` takes time to finish, and it is likely
                    # to exceed 5s time limit for a Weixin reply.  I can't
                    # find a solution right now, may there will be one later.
                    u.init_data()

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
