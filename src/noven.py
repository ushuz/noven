# -*- coding:utf-8 -*-

import base64
import functools
import hashlib
import logging
import os
import re
import time
import urllib

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
from libs import requests


# ----------------------------------------------------------------------
# Useful little helpers


def authenticated(method):
    """Decorate methods with this to require that the user be logged in."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.current_user:
            self.clear_all_cookies()
            raise tornado.web.HTTPError(444)
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
            404: "你要的东西不在这儿。",

            # 421 for wrong usercode or password
            421: "学号或教务系统密码有误。",

            # 422 for wrong mobile or password
            422: "手机号码或飞信密码有误。<br />"
                 "若忘记飞信密码，请编辑新密码发送至12520050。",

            # 423 for non-CMCC mobile
            423: "仅支持中国移动号码。",

            # 424 for duplicate sign-up
            424: "别淘气，你已经登记过了~",

            # 425 for activation
            425: "验证码有误。",

            # 426 for blocked
            426: "你已被 Noven 屏蔽，请勿再次尝试。",

            # 427 for encountering Fetion verification
            427: "飞信状态异常，请留空手机号码和飞信密码。",

            # 444 for unknown
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
        total = self.kv.get_info()["total_count"] / 2
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
            raise tornado.web.HTTPError(444)

        # Check mobile.
        if mcode and (len(mcode) != 11 or not mcode.isdigit()):
            self.log.error("%s - Invalid mobile: %s.", ucode, mcode)
            raise tornado.web.HTTPError(422)

        # Check fetion password
        if mcode and not mpass:
            self.log.error("%s - No fetion password: %s", ucode, mcode)
            raise tornado.web.HTTPError(422)

        # Check carrier
        pattern = r"^1(3[4-9]|47|5[0-2]|5[7-9]|8[2-4]|8[7-8])\d{8}"
        if mcode and not re.match(pattern, mcode):
            self.log.error("%s - Non-CMCC mobile: %s", ucode, mcode)
            raise tornado.web.HTTPError(423)

        # Check duplicate sign-up
        # Duplicate means 1 weixin 2 profiles.
        # 2 weixin 1 profile is not my concern.
        uc = self.kv.get(str(t))
        if uc and uc != ucode:
            self.log.error("%s - Duplicate sign-up.", ucode)
            raise tornado.web.HTTPError(424)

        # Check blocked user and weixin
        # b = self.kv.get(utf8("block:"+ucode)) or self.kv.get(utf8("block:"+t))
        # if b:
        #     self.log.error("%s - Blocked: %s", ucode, _unicode(b))
        #     raise tornado.web.HTTPError(426)

        try:
            # 9 digits for BJFU
            if len(ucode) == 9:
                new_user = alpha.User(ucode, upass, mcode, mpass, t)
            # 10 digits for ZJU
            elif len(ucode) == 10:
                new_user = beta.User(ucode, upass, mcode, mpass, t)
        except (alpha.AuthError, beta.AuthError) as e:
            self.log.error("%s - %s", ucode, e)
            raise tornado.web.HTTPError(421)
        except Exception as e:
            self.log.error("%s - %s (%s)", ucode, e, upass)
            raise tornado.web.HTTPError(500)

        self.set_secure_cookie("uc", ucode)

        TPL_VCODE = u"""Hello，%s！您的登记验证码：%s [Noven]"""
        if new_user.mobileno and new_user.mobilepass:
            # If  usercode and password are OK, then we should send activation
            # code.  SMS should be sent synchronously in order to redirect the
            # user to error page when shit happens.
            n = utf8(new_user.mobileno)
            p = utf8(new_user.mobilepass)

            cookie = self._new_cookie["uc"].value
            vcode = str(int(hashlib.sha1(cookie).hexdigest(), 16))[:6]
            c = utf8(TPL_VCODE % (new_user.name, vcode))

            fetion = NovenFetion.Fetion(n, p)
            while True:
                try:
                    fetion.login()
                    fetion.send_sms(c)
                    fetion.logout()
                except NovenFetion.AuthError as e:
                    self.log.error("%s - %s", ucode, e)
                    raise tornado.web.HTTPError(422)
                except NovenFetion.Critical as e:
                    self.log.critical("%s - %s", ucode, e)
                    raise tornado.web.HTTPError(427)
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
            # self.log.info("%s - Activated.", ucode)
            self.redirect("/welcome")
        else:
            self.log.critical("%s - Invalid user object.", ucode, e)
            raise tornado.web.HTTPError(444)


class VerifyHandler(SignUpHandler):
    @authenticated
    def get(self):
        self.render("verify.html")

    @authenticated
    def post(self):
        v = self.get_argument("vcode", None)
        o = str(int(hashlib.sha1(self.get_cookie("uc")).hexdigest(), 16))[:6]
        u = self.current_user

        if v.isdigit() and v == o:
            u.verified = True
            self.kv.set(utf8(u.usercode), u)
            self.redirect("/welcome")
        else:
            self.log.error("%s - Invalid activation code.", u.usercode)
            raise tornado.web.HTTPError(425)


class WelcomeHandler(SignUpHandler):
    @authenticated
    def get(self):
        u = self.current_user
        if u.verified:
            self.render("welcome.html")

            # Return if the user is already initialized (to avoid unnecessary
            # re-initialization when the user refresh welcome page).
            # Won't work if the user have no courses.
            if len(u.courses):
                return

            # Here `init()` could be async.
            try:
                u.init()
            except Exception as e:
                # Logout after exceptions
                u._logout()
                self.log.critical("%s - %s", u.usercode, e)

            self.kv.set(utf8(u.usercode), u)

            l = [
                "Code: %s" % u.usercode,
                "Name: %s" % u.name,
                "GPA: %s" % u.GPA,
                "Courses: %d" % len(u.courses),
            ]

            if u.mobileno and u.mobilepass:
                wellinfo = utf8(create_message(u.TPL_WELCOME, u=u))
                wellinfo = base64.b64encode(wellinfo)
                sae.taskqueue.add_task(
                    "message_queue",
                    "/backend/sms/%s" % u.usercode,
                    wellinfo
                )
                l.append("Mobile: %s" % u.mobileno)

            if u.wx_id:
                self.kv.set(utf8(u.wx_id), utf8(u.usercode))

            # Notie
            content = utf8("\n".join(l))
            title = "New User"
            pl = urllib.urlencode({"t": title, "c": content})
            sae.taskqueue.add_task("message_queue", "/backend/notie", pl)

            self.log.info("%s - Name: %s Courses: %d", u.usercode,
                          u.name, len(u.courses))
        else:
            self.log.critical("In-Active users accessing welcome page.")
            raise tornado.web.HTTPError(444)


class ReportHandler(BaseHandler):
    """Display users' reports."""
    def get(self):
        t = self.get_argument("t", None)
        s = self.get_argument("s", None)
        n = self.get_argument("n", None)

        # Get logger before logging.
        log = logging.getLogger("Noven.Report")

        # Authenticate the user.
        # Turn down illegal accesses by 444.  If shit happened to normal
        # users, 444 can guide them to contact Noven.
        if not t or not s or not n or create_signature(t[:20]+n[-8:]) != s:
            log.error("%s - Illegal access.", t)
            raise tornado.web.HTTPError(444)

        uc = self.kv.get(utf8(t))
        # Check if usercode was successfully retrieved.
        if not uc:
            log.critical("%s - Failed to retrieve usercode.", t)
            raise tornado.web.HTTPError(444)

        # Token expires in 30 min.
        # Tell users their Token expired by 401.
        if time.time() - float(n) > 1800:
            log.debug("%s - Token expired.", uc)
            raise tornado.web.HTTPError(401)

        u = self.kv.get(uc)
        # Check if User object was successfully retrieved.
        if not u:
            log.critical("%s - Failed to retrieve user.", uc)
            raise tornado.web.HTTPError(444)

        u.terms = sorted(list(set([c.term for c in u.courses.values()])),
                         reverse=True)
        self.render("report.html", u=u)
        log.debug("%s - %s's report accessed.", uc, u.name)


# ----------------------------------------------------------------------
# Brand new WxHandler


class WxHandler(TaskHandler):
    def get(self):
        s = self.get_argument("echostr", None)
        if s:
            self.write(utf8(s))
            return

    def post(self):
        msg = self.msg = NovenWx.parse(self.request.body)

        if not msg:
            return

        log = logging.getLogger("Noven.Weixin")

        if isinstance(msg, NovenWx.BlahMessage):
            self.reply(u"收到！")
            return

        # Check user's existence so we WON'T need to check it in every logic.
        u = self.current_user
        if not u:
            if isinstance(msg, NovenWx.HelloMessage):
                self.reply("bonjour")
            else:
                self.reply(u"请先登记")
            return

        # Score query
        if isinstance(msg, NovenWx.QueryMessage):
            if u.wx_push:
                # TPL_NEW_COURSES
                self.reply(create_message(u.TPL_NEW_COURSES, u=u,
                                          new_courses=u.wx_push))
                u.wx_push = {}
                self.kv.set(utf8(u.usercode), u)
                return
            else:
                # TPL_NO_UPDATE
                self.reply(create_message(u.TPL_NO_UPDATE, u=u))
                return

        # Report request
        if isinstance(msg, NovenWx.ReportMessage):
            self.reply("report")
            return

        # Un-Subscribe event.
        # Delete users when they un-subscribe.  Block them manually if needed.
        if isinstance(msg, NovenWx.ByeMessage):
            # self.kv.delete(utf8(u.wx_id))
            self.kv.delete(utf8(u.usercode))

            # s = "|".join([time.strftime("%Y%m%d"), "WX:"+u.wx_id, "Un-Subscribe"])
            # self.kv.set(utf8("block:"+u.wx_id), _unicode(s))

            log.info("%s - Deleted: Un-Subscribe.", u.usercode)
            return

    def get_current_user(self):
        uc = self.kv.get(utf8(self.msg.fr))
        if not uc:
            return
        u = self.kv.get(uc)
        return u

    def check_xsrf_cookie(self):
        # POSTs are made by Tencent servers, so XSRF COOKIE doesn't exist.
        # Checking XSRF COOKIE becomes unnecessary under such condition.
        # While Weixin has offered a way to authenticate the POSTs, which
        # can be implemented here later if it is needed.
        pass

    def reply(self, content):
        msg = self.msg
        if content == "bonjour":
            self.render("bonjour.xml", to=msg, create_signature=create_signature)
        elif content == "report":
            self.render("report.xml", to=msg, create_signature=create_signature)
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

        prefixes = ("3", "1")
        total = 0
        for prefix in prefixes:
            ucs = self.kv.getkeys_by_prefix(prefix, limit=5000, marker=marker)
            try:
                uc = ""
                for uc in ucs:
                    sae.taskqueue.add_task("update_queue", "/backend/update/%s" % uc)
                    total += 1
            except sae.kvdb.Error as e:
                # KVDB is annoying.  We may encounter different errors, such as `Timed
                # Out`, `No Server Available`, etc.  We should just continue from here.
                sae.taskqueue.add_task("update_queue", "/backend/update?marker=%s" % uc)

        # Notie
        title = "Update Started"
        content = utf8("%d tasks added." % total)
        pl = urllib.urlencode({"t": title, "c": content})
        sae.taskqueue.add_task("message_queue", "/backend/notie", pl)


class UpdateById(TaskHandler):
    def get(self, id):
        log = logging.getLogger("Noven.Update")

        u = self.kv.get(utf8(id))
        if not u:
            # Can't get user from KVDB.
            log.error("%s - User not exists.", id)
            raise tornado.web.HTTPError(404)
        if not u.verified:
            # User is not activated.
            # log.error("%s - User not activated.", id)
            raise tornado.web.HTTPError(425)

        # Debug settings
        if "SERVER_SOFTWARE" not in os.environ:
            alpha.DATA_URL = "http://127.0.0.1:8888/data"
            beta.DATA_URL = "http://127.0.0.1:8888/xscj.aspx?xh=%s"

        try:
            new_courses = u.update()
        except (alpha.AuthError, beta.AuthError) as e:
            log.error("%s - %s", id, e)
            # User changed their password for sure. Delete them.
            # if u.wx_id: self.kv.delete(utf8(u.wx_id))
            self.kv.delete(utf8(u.usercode))
            log.info("%s - Deleted: User changed password.", id)
            raise tornado.web.HTTPError(421)
        except Exception as e:
            log.error("%s - %s", id, e)
            raise tornado.web.HTTPError(500)

        if new_courses:
            log.info("%s - %s has %s updates. GPA %s.",
                     id, u.name, len(new_courses), u.GPA)

            # If `u.wx_id` exists, we should update `u.wx_push` with `new_courses`
            # so that we can return it when users performs a score query by Weixin,
            # no matter `u.mobileno` exists or not.
            if u.wx_id:
                u.wx_push.update(new_courses)

            # If `u.mobileno` exists, we should notify the user via SMS.
            if u.mobileno:
                noteinfo = utf8(create_message(u.TPL_NEW_COURSES, u=u,
                                               new_courses=new_courses))
                noteinfo = base64.b64encode(noteinfo)
                sae.taskqueue.add_task(
                    "message_queue",
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
            raise tornado.web.HTTPError(404)

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
                # Users had changed Fetion password.  Delete their mobile and
                # fetion password.
                u.mobileno = None
                u.mobilepass = None
                self.kv.set(utf8(id), u)
                log.info("%s - Updated: User changed Fetion password.", id)
                raise tornado.web.HTTPError(422)
            except NovenFetion.Critical as e:
                log.critical("%s - %s", id, e)
                raise tornado.web.HTTPError(427)
            except Exception:
                continue
            break

        log.info("%s - SMS Sent to %s.", id, n)

    def check_xsrf_cookie(self):
        pass


class NotieHandler(TaskHandler):
    """Push notifications through Notie.

    Mainly for two purposes:
        1. New User
        2. Update Summary
    """
    def post(self):
        title = self.get_argument("t")
        content = self.get_argument("c")
        action = self.get_argument("a", "Fly Me To The Moon")

        url = "https://io.notie.io"

        data = {
            "source_id": 42,
            "secret": "e850caf0c9d",

            "title": title,
            "action": action,
            "content": content,
        }

        r = requests.post(url, data=data, verify=False)

        self.write(r.json())

    def check_xsrf_cookie(self):
        pass
