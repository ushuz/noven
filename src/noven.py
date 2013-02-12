# -*- coding:utf-8 -*-

import sae
import sae.kvdb
import sae.taskqueue
import tornado.web

import urllib
import hashlib
import functools

#import the main part and third-part libs for the app
from libs import alpha2 as alpha
from libs import NovenFetion
from libs import NovenWx

NO_UPDATE_TEMPLATE = u'''Hello，%s！自上次查询以来还没有课出分。当前学期您的学分积为%s，全学程您的学分积为%s，%s。'''
NEW_COURSES_TEMPLATE = u'''Hello，%s！有%d门课出分了，分别是%s。当前学期您的学分积为%s，全学程您的学分积为%s，%s。[Noven]'''
VCODE_MESSAGE_TEMPLATE = u'''Hello，%s！您的登记验证码：%s [Noven]'''
WELCOME_MESSAGE_TEMPLATE = u'''Hello，%s！全学程您的学分积为%s，%s，共修过%d门课。加油！[Noven]'''

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


# Override default error handler to display costumized error pages
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


class SignupHandler(BaseHandler):
    def get(self):
        self.render("signup.html", total=self.kv.get_info()["total_count"])

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
        if new_user.name and self.kv.set(new_user.usercode.encode("utf-8"), new_user):    #set() only takes str as key, WTF!
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
            "c": (VCODE_MESSAGE_TEMPLATE % (self.current_user.name, hashlib.sha1(self.get_cookie("uc")).hexdigest()[:6])).encode("utf-8")
        }
        # for template debug
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
            wellinfo = {
                "n": self.current_user.mobileno,
                "p": self.current_user.mobilepass,
                "c": (WELCOME_MESSAGE_TEMPLATE % (u.name, u.GPA, u.rank, len(u.courses))).encode("utf-8")
            }
            sae.taskqueue.add_task("send_verify_sms_task", "/backend/sms", urllib.urlencode(wellinfo))
        else:
            self.redirect("/")


class SorryHandler(BaseHandler):
    def get(self):
        error = "请检查学号、密码、手机号、飞信密码及验证码是否输入有误。"
        self.render("sorry.html", error = error)


class UpdateTaskHandler(BaseHandler):
    def get(self):
        userlist = [ut[1] for ut in self.kv.get_by_prefix("") if isinstance(ut[1], alpha.User)]
        for u in userlist:
            # if wx_id exists, sms should not be sent
            if not u.verified or not u.name:
                continue

            new_courses = u.update()
            
            #debug
            new_courses = {"20122测试课程": alpha.Course(subject=u"测试课程", score=u"90", point=u"3.0", term=u"20122")}
            # self.kv.set(u.usercode.encode("utf-8"), u)
            #debug
            
            if new_courses:
                if u.wx_id:
                    u.wx_push.update(new_courses)
                    self.kv.set(u.usercode.encode("utf-8"), u)
                    continue
                
                self.kv.set(u.usercode.encode("utf-8"), u)
                tosend = u"、".join([u"%s(%s)" % (v.subject, v.score) for v in new_courses.values()])

                noteinfo = {
                    "n": u.mobileno,
                    "p": u.mobilepass,
                    "c": (NEW_COURSES_TEMPLATE % (u.name, len(new_courses), tosend, u.current_GPA, u.GPA, u.rank)).encode("utf-8")
                }
                sae.taskqueue.add_task("send_notification_sms_task", "/backend/sms", urllib.urlencode(noteinfo))


class SMSTaskHandler(BaseHandler):
    def post(self):
        n = self.get_argument("n").encode("utf-8") #mobile number
        p = self.get_argument("p").encode("utf-8") #fetion password
        c = self.get_argument("c").encode("utf-8") #SMS content

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
        
        print "%s - SMS sent." % n

    get = post

    def check_xsrf_cookie(self):
        pass


class UpgradeHandler(BaseHandler):
    def get(self):
        userlist = [ut[1] for ut in self.kv.get_by_prefix("") if isinstance(ut[1], alpha.User)]
        for user in userlist:
            u = alpha.User(user.usercode, user.password, user.mobileno, user.mobilepass)
            u.name, u.GPA, u.rank, u.verified, u.courses = user.name, user.GPA, user.rank, user.verified, user.courses
            self.kv.set(user.usercode.encode("utf-8"), u)
            print "%s upgraded" % u.usercode.encode("utf-8")

class WxHandler(BaseHandler):
    def get(self):
        self.write(self.get_argument("echostr", None).encode("utf-8"))
    
    def post(self):
        msg = NovenWx.parse(self.request.body)
        
        if isinstance(msg, NovenWx.SignupMessage):
            # sign up logic
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
                    u.init_data()
                else:
                    self.reply(msg, u"登记失败！请检查学号、密码是否输入有误。")
                    return

            self.kv.set(u.usercode.encode("utf-8"), u)    #set() only takes str as key, WTF!
            self.kv.set(msg.fr.encode("utf-8"), u.usercode.encode("utf-8"))
            self.reply(msg, (WELCOME_MESSAGE_TEMPLATE % (u.name, u.GPA, u.rank, len(u.courses)))[:-7])
            return
        
        if isinstance(msg, NovenWx.HelloMessage):
            # return guide
            guide = u"\r\n".join([u"欢迎通过微信使用Noven！",
                                  u"登记：发送“ZC 学号 密码”（请用空格隔开，不包括引号）", 
                                  u"查询：登记后发送任意内容即可查询最近出分状况",
                                  u"注意：若您已在网站登记，微信登记后短信通知将随即终止"])
            self.reply(msg, guide)
            return

        if isinstance(msg, NovenWx.QueryMessage):
            # score query logic
            uc = self.kv.get(msg.fr.encode("utf-8"))
            if uc:
                u = self.kv.get(uc)
                if u.wx_push:
                    tosend = u"、".join([u"%s(%s)" % (v.subject, v.score) for v in u.wx_push.values()])
                    self.reply(msg, (NEW_COURSES_TEMPLATE % (u.name, len(u.wx_push), tosend, u.current_GPA, u.GPA, u.rank))[:-7])
                    u.wx_push = {}
                    self.kv.set(u.usercode.encode("utf-8"), u)
                else:
                    self.reply(msg, NO_UPDATE_TEMPLATE % (u.name, u.current_GPA, u.GPA, u.rank))
            else:
                self.reply(msg, u"您还没有登记！请发送“ZC 学号 密码”（请用空格隔开，不包括引号）进行登记。")
        else:
            # exception handler
            # unknown message received
            pass
        
        
    def check_xsrf_cookie(self):
        pass
    
    def reply(self, received, content):
        self.write(NovenWx.reply(received, content))