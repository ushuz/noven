# -*- coding:utf-8 -*-

import functools
import logging
import re
import time

import requests
import vpn


ALL_TERMS = True
NAME_URL = "http://202.204.115.67/xueshengxinxichaxun/query.asp"

# Direct access URL
LOGIN_URL = "http://jwxt.bjfu.edu.cn/jwxt/logon.asp"
DATA_URL = "http://jwxt.bjfu.edu.cn/jwxt/Student/StudentGraduateInfo.asp"
LOGOUT_URL = "http://jwxt.bjfu.edu.cn/jwxt/logoff.asp"

# Corresponding URL when using VPN
LOGIN_URL = "https://vpn.bjfu.edu.cn/jwxt/,DanaInfo=jwxt.bjfu.edu.cn+logon.asp"
DATA_URL = "https://vpn.bjfu.edu.cn/jwxt/Student/,DanaInfo=jwxt.bjfu.edu.cn+StudentGraduateInfo.asp"


class AuthError(Exception):
    """Wrong usercode or password."""


class Course(dict):
    """Wrapper for a course.

    :subject
    :score
    :point
    :term
    """
    PROPERTIES = ("subject", "score", "point", "term")

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
    """Providing userful methods and storage for a user."""

    TPL_NEW_COURSES = u"""Hello，{{ u.name }}！有{{ len(new_courses) }}门课出分了：{{ u"、".join([u"%s(%s)" % (v.subject, v.score) for v in new_courses.values()]) }}。当前学期您的学分积为{{ u.current_GPA }}，全学程您的学分积为{{ u.GPA }}，{{ u.rank }}。"""
    TPL_WELCOME = u"""Hello，{{ u.name }}！全学程您的学分积为{{ u.GPA }}，{{ u.rank }}，共修过{{ len(u.courses) }}门课。加油！"""
    TPL_NO_UPDATE = u"""Hello，{{ u.name }}！最近没有新课程出分。当前学期您的学分积为{{ u.current_GPA }}，全学程您的学分积为{{ u.GPA }}，{{ u.rank }}。"""

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
        self.current_GPA = u"0"
        self.rank = u"暂无排名"
        self.verified = False

        self._session = None

        self._login()
        self._get_name()
        self._logout()

    def _open(self, url, data=None):
        """Loop until a response got.

        It will return a response eventually unless the URL is unreachable and
        the thread will be dead.
        """
        o = self._session.post if data else self._session.get

        retry = 5
        while retry:
            try:
                r = o(url, data=data, verify=False, timeout=10)
            except Exception as e:
                retry -= 1
                log.debug("%s - %s", self.usercode, e)
                continue
            return r
        raise Exception("Connection timeout.")

    def _login(self):
        # self._session = requests.session()
        # We use VPN session to perform HTTP requests
        import sae.kvdb
        kv = sae.kvdb.KVClient()

        s = kv.get("VPN_SESSION")
        if not s or s.expired:
            s = vpn.Session()
            kv.set("VPN_SESSION", s)
        self._session = s

        payload = {
            "type": "Logon", "B1": u" 提　交 ".encode("gbk"),
            "UserCode": self.usercode,
            "UserPassword": self.password
        }
        r = self._open(LOGIN_URL, data=payload)
        t = r.content.decode("gbk")

        # `requests.Session` can NOT be serialized properly in KVDB. We must
        # clean it up before save.
        if u"密码不正确" in t:
            self._logout()
            raise AuthError("Wrong password.")
        if u"用户不存在" in t:
            self._logout()
            raise AuthError("Wrong usercode.")

    def _logout(self):
        # Session should be cleared in case of bad things.
        self._session = None
        pass

    def _get_name(self):
        """Save and return the user's true name."""
        r = self._open(NAME_URL, data={"xh": self.usercode})

        pattern = u"""<td>(.+?)\s*</td>"""
        m = re.findall(pattern, r.content.decode("gbk"))

        if m:
            self.name = m[1]
            log.debug("%s - Name found: %s", self.usercode, self.name)
            return self.name
        else:
            # Try again
            self._get_name()

    def _get_GPA(self, r, all=False):
        """Save and return all-term GPA or current-term GPA respectly."""
        pattern = u"<p>在本查询时间段，你的学分积为(.+?)、必修课取"
        m = re.search(pattern, r.content.decode("gbk"))
        if m:
            if all:
                self.GPA = m.group(1)
                log.debug("%s - GPA updated: %s", self.usercode, self.GPA)
                return self.GPA
            else:
                self.current_GPA = m.group(1)
                log.debug("%s - Current GPA updated: %s",
                          self.usercode, self.current_GPA)
                return self.current_GPA

    def _get_courses(self, r):
        """Save and return newly-released courses, save rank as well."""
        # If user not regisered yet, then we can't fetch any data.
        # Remember to logout before raise.
        if u"你还没有学期注册" in r.content.decode("gbk"):
            self._logout()
            raise Exception("User not registered.")

        # Import BeautifulSoup to deal with the data we got.
        from BeautifulSoup import BeautifulSoup
        soup = BeautifulSoup(r.content)

        l = soup.findAll('tr', height='25')
        if not l:
            # IndexError sometimes occurs when saving rank.  It appears that
            # malformed response we received is to blame, i.e. `r.content` is
            # not completed.  We should raise here to exit as try...except
            # is set in higher level.
            log.debug(
                "%s - Something wrong with the returned data.", self.usercode)
            raise Exception("Data corrupted.")

        # Save the rank calculated by JWXT.
        # If failed, turn to default.  Most probably, the user is in his first
        # term.
        try:
            self.rank = unicode(l[-1].contents[1].contents[2].string[5:]) \
                if u"全学程" in l[-1].contents[1].contents[2].string \
                else unicode(l[-1].contents[1].contents[3].string[5:])
        except Exception as e:
            log.debug("%s - Can't get rank for the user.", self.usercode)

        log.debug("%s - Rank saved: %s", self.usercode, self.rank)

        # Delete unnecessary data.
        del l[0]
        del l[-4:]

        new_courses = {}
        courses = self.courses.values()
        for i in l:
            if len(i.contents) < 4:
                log.debug("%s - Too few `i.contents`.", self.usercode)
                continue

            # Normal cases.
            if i.contents[1].string != u"&nbsp;" \
                    and i.contents[3].get("colspan") != u"5":
                # When [期末] is empty, we turn to [备注].
                _score = i.contents[3].contents[0].string \
                    if i.contents[3].contents[0].string \
                    else i.contents[9].contents[0].string

                course = Course(
                    subject=unicode(i.contents[1].string.strip()),
                    score=unicode(_score),
                    point=unicode(i.contents[11].string),
                    term=unicode(i.contents[13].string + i.contents[15].string)
                )

                # In some cases the user may retake and study a
                # same-name-course in a term, e.g. user:120824114 - [大学英语].
                # There will be 2 courses and they have same name and term and
                # can not be saved at the same time. So, if [选课类型] is [重修],
                # we append a flag to the key.
                _type = unicode(i.contents[19].contents[0].string) \
                    if i.contents[19].contents else u""

                key = course.term + course.subject + _type
                if course not in courses or key not in self.courses:
                    new_courses[key] = course
                    log.debug("%s - Course: %s", self.usercode, key)

            # Special cases.
            # If the course is released before Rating System been closed,
            # score will not be displayed.
            elif i.contents[3].get('colspan') == u'5':
                course = Course(
                    subject=unicode(i.contents[1].string.strip()),
                    score=u'待评价',
                    point=u'-',
                    term=unicode(i.contents[5].string + i.contents[7].string)
                )

                # In some cases the user may retake and study a
                # same-name-course in a term, e.g. user:120824114 - [大学英语].
                # There will be 2 courses and they have same name and term and
                # can not be saved at the same time. So, if [选课类型] is [重修],
                # we append a flag to the key.
                _type = unicode(i.contents[11].contents[0].string) \
                    if i.contents[11].contents else u""

                key = course.term + course.subject + _type
                if key not in self.courses:
                    new_courses[key] = course
                    log.debug("%s - Course: %s", self.usercode, key)

            else:
                # If no course was created, we should simply continue in case
                # of encountering NameError later.
                continue

        # Check Graduation Project
        pattern = u"""题目：(.+?)<br>\s*导师：(.+?)<br>\s*成绩：(.+?)"""
        m = re.search(pattern, r.content.decode("gbk"))
        if m:
            # print m.groups()
            subject, _, score = m.groups()
            course = Course(
                subject=subject,
                score=score,
                point=u"-",
                # Graduation Project will only be released in the second term.
                term="%d2" % (time.gmtime().tm_year - 1),
            )
            key = course.term + course.subject
            if course not in courses or key not in self.courses:
                new_courses[key] = course
                log.debug("%s - Course: %s", self.usercode, key)

        # Save newly-released courses.
        self.courses.update(new_courses)
        return new_courses

    def _fetch_now(self):
        return self._open(DATA_URL)

    def _fetch_all(self):
        payload = {
            "order": "xn", "by": "DESC", "year": "0", "term": "0",
            "keyword": "", "Submit1": u" 查 询 ".encode("gbk")
        }
        return self._open(DATA_URL, data=payload)

    def init(self):
        """Initialize the user's data."""
        self._login()

        # Initializing data.
        # Get `courses` and `GPA`
        r = self._fetch_all()

        self._get_courses(r)
        self._get_GPA(r, ALL_TERMS)

        # Get `current_GPA`
        r = self._fetch_now()
        self._get_GPA(r)

        log.debug("%s - %s has %d courses in total.", self.usercode,
                  self.name, len(self.courses))

        self._logout()

    def update(self):
        """Update & return newly-released courses for external call."""
        self._login()

        # Get `new_courses`
        r = self._fetch_all()

        new_courses = self._get_courses(r)
        self._get_GPA(r, ALL_TERMS)

        # Only if we got new courses should we update GPAs.
        if new_courses:
            r = self._fetch_now()
            self._get_GPA(r)

            log.debug("%s - %s has %d new courses.", self.usercode,
                      self.name, len(new_courses))

        self._logout()
        return new_courses


# Get logger before logging.
log = logging.getLogger("alpha")

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s,%(msecs)d - %(levelname)s [%(name)s] %(message)s",
        level=logging.DEBUG, datefmt="%H:%M:%S")
    logging.getLogger("requests").setLevel(logging.WARNING)
