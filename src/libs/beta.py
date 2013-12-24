# -*- coding:utf-8 -*-

import re
import logging

import requests


LOGIN_URL = "http://jwbinfosys.zju.edu.cn/default2.aspx"
DATA_URL = "http://jwbinfosys.zju.edu.cn/xscj.aspx?xh=%s"


class AuthError(Exception):
    """Wrong usercode or password."""


class Course(dict):
    """Wrapper for a course.

    :subject
    :score
    :point
    :grade
    :term
    """
    PROPERTIES = ("subject", "score", "point", "grade", "term")

    def __getattr__(self, property):
        if property in self.PROPERTIES:
            return self[property]
        else:
            return object.__getattribute__(self, property)

    def __eq__(self, other):
        for k, v in self.items():
            if v != other[k]:
                return False
        return True


class User(object):
    global LOGIN_URL
    global DATA_URL

    TPL_NEW_COURSES = u"""Hello，{{ u.name }}！有{{ len(new_courses) }}门课出分了：{{ u"、".join([u"%s(%s,%s)" % (v.subject, v.score, v.grade) for v in new_courses.values()]) }}，当前您的平均绩点为{{ u.GPA }}，已修学分{{ sum([float(v.point) for v in u.courses.values()]) }}。"""
    TPL_WELCOME = u"""Hello，{{ u.name }}！当前您的平均绩点为{{ u.GPA }}，共修过{{ len(u.courses) }}门课。加油！"""
    TPL_NO_UPDATE = u"""Hello，{{ u.name }}！最近没有新课程出分。当前您的平均绩点为{{ u.GPA }}，已修学分{{ sum([float(v.point) for v in u.courses.values()]) }}。"""

    def __init__(self, ucode, upass, mcode=None, mpass=None, wid=None):
        self.usercode = ucode
        self.password = upass
        self.mobileno = mcode
        self.mobilepass = mpass

        self.wx_id = wid
        self.wx_push = {}

        self.name = None
        self.courses = {}
        self.GPA = u"0"

        self.verified = False

        self._session = None

        self._init()

    def _open(self, url, data=None):
        """Loop until a response got.

        It will return a response eventually unless the URL is unreachable and
        the thread will be dead.
        """
        o = self._session.post if data else self._session.get

        while True:
            try:
                r = o(url, data=data)
            except:
                continue
            return r

    def _login(self):
        self._session = requests.session()

        payload = {
            "__EVENTTARGET": "Button1",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": "dDwxOTEwMzI3NDAyOzs+hurYK255qc/CsDx7/bCGtJreiuI=",
            "TextBox1": self.usercode,
            "TextBox2": self.password,
            "Textbox3": "",
            "RadioButtonList1": u"学生".encode("gb2312"),
            "Text1": ""
        }

        r = self._open(LOGIN_URL, payload)
        if not "grxx" in r.content:
            # `requests.Session` can NOT be serialized properly in KVDB. We must
            # clean it up before save.
            self._logout()
            if u"欠费".encode("gb2312") in r.content:
                raise Exception("Wrong user status.")
            if u"密码错误".encode("gb2312") in r.content:
                raise AuthError("Wrong password.")
            if u"用户名不存在".encode("gb2312") in r.content:
                raise AuthError("Wrong usercode.")
            raise Exception("Unknown: %d %s %r" % (r.status_code, r.url, r.history))

    def _logout(self):
        # Session should be cleared in case of bad things.
        self._session = None

    def _fetch(self):
        payload = {
            "__VIEWSTATE": "dDwyMTQ0OTczMjA5O3Q8O2w8aTwxPjs+O2w8dDw7bDxpPDI+O" \
                "2k8NT47aTwyMT47aTwyMz47aTwzNz47aTwzOT47aTw0MT47aTw0Mz47PjtsP" \
                "HQ8dDw7dDxpPDE0PjtAPFxlOzIwMDEtMjAwMjsyMDAyLTIwMDM7MjAwMy0yM" \
                "DA0OzIwMDQtMjAwNTsyMDA1LTIwMDY7MjAwNi0yMDA3OzIwMDctMjAwODsyM" \
                "DA4LTIwMDk7MjAwOS0yMDEwOzIwMTAtMjAxMTsyMDExLTIwMTI7MjAxMi0yM" \
                "DEzOzIwMTMtMjAxNDs+O0A8XGU7MjAwMS0yMDAyOzIwMDItMjAwMzsyMDAzL" \
                "TIwMDQ7MjAwNC0yMDA1OzIwMDUtMjAwNjsyMDA2LTIwMDc7MjAwNy0yMDA4O" \
                "zIwMDgtMjAwOTsyMDA5LTIwMTA7MjAxMC0yMDExOzIwMTEtMjAxMjsyMDEyL" \
                "TIwMTM7MjAxMy0yMDE0Oz4+Oz47Oz47dDx0PHA8cDxsPERhdGFUZXh0Rmllb" \
                "GQ7RGF0YVZhbHVlRmllbGQ7PjtsPHh4cTt4cTE7Pj47Pjt0PGk8Nz47QDxcZ" \
                "Tvnp4s75YasO+efrTvmmKU75aSPO+efrTs+O0A8XGU7MXznp4s7MXzlhqw7M" \
                "Xznn607MnzmmKU7MnzlpI87Mnznn607Pj47Pjs7Pjt0PHA8O3A8bDxvbmNsa" \
                "WNrOz47bDx3aW5kb3cucHJpbnQoKVw7Oz4+Pjs7Pjt0PHA8O3A8bDxvbmNsa" \
                "WNrOz47bDx3aW5kb3cuY2xvc2UoKVw7Oz4+Pjs7Pjt0PEAwPDs7Ozs7Ozs7O" \
                "zs+Ozs+O3Q8QDA8Ozs7Ozs7Ozs7Oz47Oz47dDxAMDw7Ozs7Ozs7Ozs7Pjs7P" \
                "jt0PHA8cDxsPFRleHQ7PjtsPFpKRFg7Pj47Pjs7Pjs+Pjs+Pjs+y0ElZ9Hn+" \
                "SlXToKugoUwAneDL5w=",
            "ddlXN": "",
            "ddlXQ": "",
            "txtQSCJ": "",
            "txtZZCJ": "",
            "Button2": u"在校学习成绩查询".encode("gb2312")
        }
        url = DATA_URL % self.usercode
        return self._open(url, payload).content.decode("gbk")

    def _get_name(self, data):
        pattern = u"""<span id="Label5">姓名：(.+?)</span>"""
        m = re.search(pattern, data)
        if m:
            self.name = m.groups()[0]
            log.debug("%s - Name found: %s", self.usercode, self.name)
            return self.name

    def _get_courses(self, data):
        from BeautifulSoup import BeautifulSoup
        soup = BeautifulSoup(data)

        l = soup.find("table", id="DataGrid1").contents

        del l[0:2]
        del l[-1]

        new_courses = {}
        courses = self.courses.values()
        for i in l:
            if len(i.contents) != 8:
                log.debug("%s - Something wrong with `i.contents`.", self.usercode)
                continue

            # Normal cases.
            # Refer to [补考] is empty.
            score = i.contents[3].string if i.contents[6].string == u"&nbsp;" \
                else i.contents[6].string

            course = Course(
                subject = i.contents[2].string.strip(),
                score   = score,
                point   = i.contents[4].string,
                grade   = i.contents[5].string,
                term    = i.contents[1].string[1:12]
            )

            key = course.term + course.subject
            if course not in courses:
                new_courses[key] = course
                log.debug("%s - Course: %s", self.usercode, key)

        # Save newly-released courses.
        self.courses.update(new_courses)
        return new_courses

    def _get_GPA(self):
        t = 0.0
        m = 0.0
        for v in self.courses.values():
            m += float(v.point)*float(v.grade)
            t += float(v.point)
        self.GPA = u"%.2f" % (m / t)
        log.debug("%s - GPA updated: %s", self.usercode, self.GPA)
        return self.GPA

    def _init(self):
        self._login()

        data = self._fetch()
        self._get_name(data)
        self._get_courses(data)
        self._get_GPA()

        log.debug("%s - %s has %d courses in total.",
            self.usercode, self.name, len(self.courses))

        self._logout()

    def init(self):
        "Providing a fake init() interface."
        pass

    def update(self):
        self._login()

        data = self._fetch()
        new_courses = self._get_courses(data)
        if new_courses:
            self._get_GPA()
            log.debug("%s - %s has %d new courses.",
                self.usercode, self.name, len(new_courses))

        self._logout()

        return new_courses


# Get logger before logging.
log = logging.getLogger("beta")

if __name__ == "__main__":
    logging.basicConfig(format="%(levelname).1s [%(asctime).19s] %(message)s", level=logging.DEBUG)
    logging.getLogger("requests").setLevel(logging.WARNING)
