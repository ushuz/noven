# -*- coding:utf-8 -*-

import requests


LOGIN_URL = "http://f.10086.cn/huc/user/space/login.do"
SMS_URL = "http://f.10086.cn/im/user/sendMsgToMyselfs.action"
LOGOUT_URL = "http://f.10086.cn/im/index/logoutsubmit.action"


class AuthError(Exception):
    """Wrong mobile or password."""


class ConnError(Exception):
    """Failed to connect to fetion servers."""


class Critical(Exception):
    """Halt NovenFetion."""


class Fetion(object):
    """A simplified WAP Fetion.

    Only login, send_sms and logout functions reserved."""

    def __init__(self, mobile, password):
        self.mobile, self.password = mobile, password
        self.session = requests.session()

    def login(self):
        pl = {
            "mobilenum": self.mobile,
            "password": self.password,
            "m": "submit",
            "backurl": "http://f.10086.cn/im/login/cklogin.action",
            # "fr": "space"
        }

        try:
            r = self.session.post(LOGIN_URL, pl)
        except Exception:
            raise ConnError("%s - ConnError: Login" % self.mobile)

        if u"密码错误" in r.text or u"登陆失败" in r.text:
            raise AuthError("%s - AuthError: Wrong Mobile or Password" %
                            self.mobile)

        if u"验证码不能为空" in r.text:
            raise Critical("%s - Critical: Verification Required" %
                           self.mobile)

        if r.url.endswith("login.do"):
            raise Critical("%s - Critical: Login Failed" % self.mobile)

        return True

    def send_sms(self, msg):
        try:
            r = self.session.post(SMS_URL, {"msg": msg})
        except Exception:
            raise ConnError("%s - ConnError: Send SMS" % self.mobile)

        return u"发送成功" in r.text

    def logout(self):
        try:
            r = self.session.get(LOGOUT_URL)
        except:
            raise ConnError("%s - ConnError: Logout" % self.mobile)

        return u"成功退出WAP飞信" in r.text


if __name__ == "__main__":
    pass
