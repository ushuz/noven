#  -*-  coding: utf-8  -*-

import os
import sys

import requests

if len(sys.argv) == 3:
    in_path = os.path.join(os.getcwd(), sys.argv[1])
    out_path = os.path.join(os.getcwd(), sys.argv[2])

    with open(in_path) as f:
        t = f.read().decode("utf-8")

    if in_path.endswith(".js"):
        t = requests.post("http://marijnhaverbeke.nl/uglifyjs", data={"js_code": t}).text
    else:
        t = requests.post("http://cssminifier.com/raw", data={"input": t}).text

    with open(out_path, "w+") as f:
        f.write(t.encode("utf-8"))
else:
    print "usage: python min.py input_filename output_filename"