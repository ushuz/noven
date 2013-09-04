# -*- coding:utf-8 -*-

import requests

HOST = "http://f.10086.cn"


class AuthError(Exception):
    '''Wrong mobileno or password, or not logged in.'''


class ConnError(Exception):
    '''Failed to connect to fetion servers.'''


class Fetion(object):
    '''A simplified 3G Fetion.
    Only reserved login(), send_sms(), logout().'''
    global HOST

    def __init__(self, mobile, password):
        self.mobile, self.password = mobile, password
        self.session = requests.session()

    def login(self):
        '''/im5/login/loginHtml5.action
        :m
        :pass
        :captchaCode    :None
        :checkCodeKey   :null'''
        login_payload = {
            "m"              : self.mobile,
            "pass"           : self.password,
            "captchaCode"    : None,
            "checkCodeKey"   : "null"
        }
        try:
            r = self.session.post(HOST+"/im5/login/loginHtml5.action", data=login_payload)
            self.id = r.json()["idUser"]
        except:
            raise ConnError("%s - ConnError: Login" % self.mobile)

        if not self.id:
            raise AuthError("%s - AuthError: Wrong Mobile or Password" % self.mobile)

    def send_sms(self, msg):
        '''/im5/chat/sendNewGroupShortMsg.action
        :msg
        :touserid

        return sendCode
               0    - 发送失败
               200  - 发送成功'''
        if not self.id:
            raise AuthError("%s - AuthError: Not Logged In" % self.mobile)

        msg_payload = {
            "msg"       : msg,
            "touserid"  : self.id
        }

        try:
            r = self.session.post(HOST+"/im5/chat/sendNewGroupShortMsg.action", data=msg_payload)
        except:
            raise ConnError("%s - ConnError: Send SMS" % self.mobile)

        return r.json()["sendCode"]

    def logout(self):
        '''/im5/index/logoutsubmit.action'''
        try:
            r = self.session.get(HOST+"/im5/index/logoutsubmit.action")
        except:
            raise ConnError("%s - ConnError: Logout" % self.mobile)
        self.id = None


if __name__ == "__main__":
    pass
