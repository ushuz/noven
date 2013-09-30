#  -*-  coding: utf-8  -*-

import os
import sys

import requests

if len(sys.argv) == 3:
    in_path = os.path.join(os.getcwd(), sys.argv[1])
    out_path = os.path.join(os.getcwd(), sys.argv[2])

    dir, _, files = os.walk(in_path).next()

    for i in files:
        in_name = os.path.join(dir, i)
        out_name = os.path.join(out_path, i)
        with open(in_name) as f:
            t = f.read().decode("utf-8")

        if in_name.endswith(".js"):
            t = requests.post("http://marijnhaverbeke.nl/uglifyjs", data={"js_code": t}).text
        else:
            t = requests.post("http://cssminifier.com/raw", data={"input": t}).text

        with open(out_name, "w+") as f:
            f.write(t.encode("utf-8"))

        print "Minimizing  %s" % os.path.join(sys.argv[2], i)
else:
    print "usage: python min.py input_filename output_filename"