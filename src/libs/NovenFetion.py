# -*- coding:utf-8 -*-

import logging
import math
import re
import socket

import requests

from binascii import a2b_hex, b2a_hex
from hashlib import sha1
from random import randrange
from struct import pack
from string import atol


FETION_VER = "4.7.7800"
SSI_URL = "https://uid.fetion.com.cn/ssiportal/SSIAppSignInV4.aspx"
LOGIN_XML = """<args><device accept-language="default" machine-code="0A0003000000" /><caps value="1FFF" /><events value="7F" /><user-info mobile-no="%s" user-id="%s"><personal version="0" attributes="v4default;alv2-version;alv2-warn;dynamic-version" /><custom-config version="0"/><contact-list version="0" buddy-attributes="v4default" /></user-info><credentials domains="fetion.com.cn;m161.com.cn;www.ikuwa.cn;games.fetion.com.cn;turn.fetion.com.cn;pos.fetion.com.cn;ent.fetion.com.cn;mms.fetion.com.cn"/><presence><basic value="0" desc="" /><extendeds /></presence></args>"""


class AuthError(Exception):
    """Wrong mobile or password.
    """


class ConnError(Exception):
    """Failed to connect to fetion servers.
    """


class Critical(Exception):
    """Halt NovenFetion.
    """


def update_config(mobile):
    """Update proxy configuration from servers.

    It won't be necessary to update configuration in production, but we
    will need it if shit happens.
    """
    CONFIG_URL = "http://nav.fetion.com.cn/nav/getsystemconfig.aspx"
    CONFIG_XML = """<config><user mobile-no="%s" /><client type="PC" version="%s" platform="W5.1" /><servers version="0" /></config>"""

    r = requests.post(CONFIG_URL, CONFIG_XML % (mobile, FETION_VER))

    # Update SSI_URL for requesting URI
    m = re.search("<ssi-app-sign-in-v2>(.*)</ssi-app-sign-in-v2>", r.content)
    SSI_URL = m.group(1) if m else SSI_URL
    print "SSI_URL:", SSI_URL

    # Update SIPC_PROXY
    m = re.search("<sipc-proxy>(.*)</sipc-proxy>", r.content)
    SIPC_PROXY = m.group(1) if m else SIPC.SIPC_PROXY
    print "SIPC_PROXY:", SIPC_PROXY


def rsa(m, p, q, d):
    e, n = atol(p, 16), atol(q, 16)
    l = (len(q) + 1) / 2
    o, inb = l - d, l - 1 + d
    if not d:
        k = int(math.log(n) / math.log(2) / 8 + 1)
        m = '\x00\x02' + _random_bytes(k - len(m) - 3) + '\x00' + m
    ret, s = [], True
    while s:
        s = m
        m = None
        s and map(ret.extend,
                  map(lambda i, b=pow(reduce(lambda x, y: (x << 8L) + y, map(
                    ord, s)), e, n): chr(b >> 8 * i & 255), range(o-1, -1, -1)))
    ret = ''.join(ret)
    if d:
        return ret[ret.index('\x00', 2) + 1:]
    else:
        return ret


def _random_bytes(size):
    return ''.join(chr(randrange(1, 256)) for i in xrange(max(8, size)))


class SIPC(object):

    SIPC_PROXY = "221.176.30.178:8080"
    SIPC_VER = "SIP-C/4.0"
    DOMAIN = "fetion.com.cn"

    _headers = ""
    _content = ""

    Q = 1
    I = 1

    def __init__(self):
        self._tcp_init()

    def _tcp_init(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            (host, port) = tuple(self.SIPC_PROXY.split(":"))
            self._sock.connect((host, int(port)))
        except socket.error as e:
            self._sock.close()
            raise ConnError("%s - ConnError: _tcp_init" % (self.mobile))

    def get_code(self, data):
        m = re.search("%s (\d{3})" % self.SIPC_VER, data)
        code = int(m.group(1)) if m else None
        return code

    def init(self, type):
        self._headers = [
            "%s %s %s" % (type, self.DOMAIN, self.SIPC_VER),
            "F: %s" % self.sid,
            "I: %s" % self.I,
            "Q: %s %s" % (self.Q, type),
        ]

    def prepare(self, cmd, *args):
        body = args[1] if len(args) == 2 else ""

        if cmd == "REG":
            self.init("R")

            if args[0] == 1:
                self._headers.append("CN: 491c23644b7769ede1af078cb14901e2")
                self._headers.append('CL: type="pc",version="%s"' % FETION_VER)

            if args[0] == 2:
                body = LOGIN_XML % (self.mobile, self.uid)
                nonce = re.search('nonce="(.+?)"', args[1]).group(1)
                key = re.search('key="(.+?)"', args[1]).group(1)

                p1 = sha1("fetion.com.cn:"+self.password).hexdigest()
                p2 = sha1(pack("i", int(self.uid))+a2b_hex(p1)).hexdigest()
                plain = nonce + a2b_hex(p2) + \
                    a2b_hex("e146a9e31efb41f2d7ab58ba7ccd1f2958ec944a5cffdc514873986923c64567")

                resp = b2a_hex(rsa(plain, key[-6:], key[:-6][:256], False))

                self._headers.append(
                    'A: Digest algorithm="SHA1-sess-v4",response="%s"' % resp)

        if cmd == "SendCatSMS":
            self.init("M")
            self._headers.append("T: %s" % args[0])
            self._headers.append("N: %s" % cmd)

        if cmd == "DEAD":
            self.init("R")
            self._headers.append("X: 0")

        # General SIPC data
        if len(body) != 0:
            self._headers.append("L: %d" % len(body))
        self._headers.append("")
        self._headers.append(body)
        self._content = "\r\n".join(self._headers)

    def send(self):
        content = self._content
        response = ""

        log.debug("--->(tcp send)\n%s\n--->", content.decode("utf-8"))
        self._tcp_send(content)
        retry = 5
        while retry and not response:
            try:
                ret = self._tcp_recv()
            except socket.error as e:
                raise ConnError("%s - ConnError: _tcp_recv" % self.mobile)

            for rs in ret:
                log.debug("<---(tcp recv)\n%s\n<---", rs.decode("utf-8"))
                code = self.get_code(rs)
                if not code:
                    continue
                response = rs

            retry -= 1

        return response, code

    def _tcp_send(self, msg):
        try:
            self._sock.send(msg)
        except socket.error as e:
            self._sock.close()
            raise ConnError("%s - ConnError: _tcp_send" % (self.mobile))

    def _tcp_recv(self):
        """Read 1024 bytes first, read left data if there is more.

        TODO: Figure out recv mechanism and improve it.
        """
        total_data = []
        bs = 1024

        data = self._sock.recv(bs)
        total_data.append(data)

        while data:
            if re.search("L: (\d+)", data):
                break
            if data.endswith("\r\n\r\n"):
                return total_data
            data = self._sock.recv(bs)
            total_data.append(data)

        while re.search("L: (\d+)", data):
            n = len(data)
            L = int(re.findall("L: (\d+)", data)[-1])
            p = data.rfind("\r\n\r\n")
            abc = data
            data = ""
            p1 = data.rfind(str(L))

            if p < p1:
                log.critical(r"\r\n before L.")
                left = L + n - (p1 + len(str(L))) + 4
            else:
                left = L - (n - p - 4)

            if left == L:
                log.critical("It happened!")
                raise Critical("%s - Critical: Unknown" % self.mobile)

            # print left, L, n, p, p1
            # If there are more bytes than last L, eg. when it comes to
            # another command: BN, read until another L.
            if left < 0:
                log.debug("abc")
                d = ""
                left = 0
                while True:
                    d = self._sock.recv(bs)
                    data += d
                    if re.search("L: (\d+)", d):
                        break
                log.debug("read left bytes")
                log.debug("data:"+data)
                total_data.append(data)

            # Read left bytes
            while left:
                data = self._sock.recv(left)
                n = len(data)
                left -= n
                # print left, n
                if not data:
                    break
                total_data.append(data)

        return self._split("".join(total_data))

    def _split(self, data):
        """Split up several SIPC payloads in a single recv..

        When we call `send_sms`, three BN payloads will be received in a single
        recv without explicit seperation, we need to split up respectly for
        later usage.
        """
        a = data.split("\r\n\r\n")
        for i in xrange(len(a)):
            m = re.search("L: (\d+)", a[i])
            if not m:
                a[i] += "\r\n\r\n"
                continue
            L = int(m.group(1))
            a[i] += "\r\n\r\n" + a[i+1][:L]
            a[i+1] = a[i+1][L:]

        if not a[-1].strip():
            a.pop()
        return a

    def close(self):
        self._sock.close()


class Fetion(SIPC):

    def __init__(self, mobile, password):
        self.mobile = mobile
        self.password = password

    def login(self):
        """Login.

        To login, we should get URI through a HTTP request to SSI endpoint and
        then perform SIPC registration.
        """
        # Requesting URI
        params = {
            "mobileno": self.mobile,
            "domains": "fetion.com.cn;m161.com.cn;www.ikuwa.cn",
            "v4digest-type": 1,
            "v4digest": sha1("fetion.com.cn:"+self.password).hexdigest(),
        }
        r = requests.get(SSI_URL, params=params)

        log.debug("<---(http recv)\n%s\n<---", r.content.decode("utf-8"))

        # Check status code
        # When 405 is met, we perform retries at higher level.
        if r.status_code == 405:
            raise ConnError("%s - ConnError: URI Request" % self.mobile)
        if r.status_code == 400:
            raise AuthError("%s - AuthError: Wrong Mobile" % self.mobile)
        if r.status_code == 401:
            raise AuthError("%s - AuthError: Wrong Password" % self.mobile)
        if r.status_code in (404, 500):
            raise AuthError("%s - AuthError: %s" % (self.mobile, r.content))
        if r.status_code in (420, 421):
            raise Critical("%s - Critical: Verification" % self.mobile)

        body = r.content
        try:
            self.ssic = r.cookies["ssic"]
            self.sid = re.search("sip:(.+?)@", body).group(1)
            self.uri = re.search('uri="(.+?)" mobile-no', body).group(1)
            self.uid = re.search('user-id="(.+?)"', body).group(1)
        except Exception as e:
            raise ConnError("%s - ConnError: URI Parse" % self.mobile)

        # SIPC registration
        SIPC.__init__(self)

        self.prepare("REG", 1)
        response, _ = self.send()

        while True:
            self.prepare("REG", 2, response)
            ret, code = self.send()
            if code == 200:
                break
            if code == 401:
                continue
            if code in (421, 420, 494):
                raise Critical("%s - Critical: Verification" % self.mobile)
            raise ConnError("%s - ConnError: SIPC Registration" % self.mobile)

    def logout(self):
        self.prepare("DEAD")
        self.send()
        self.close()

    def send_sms(self, msg):
        """Send SMS.
        """
        to = self.uri
        self.prepare("SendCatSMS", to, msg)
        response, code = self.send()
        return code


log = logging.getLogger("NovenFetion")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
