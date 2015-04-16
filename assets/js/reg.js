// With digitOnly() users shall only input digits in UserCode & MobileNo fields.
var digitOnly = function(event) {return (/[\d]/.test(String.fromCharCode(event.charCode||event.keyCode)))};

// Validate submit data.
var checkForm = function() {
    var form = document.getElementsByTagName("form")[0];
    if (String(form.action).indexOf("verify") == -1) {
        var uc = document.getElementById("uc");
        var mc = document.getElementById("mc");
        if ((uc.value.length<9 && uc.value.length>10) || up.value.length==0) {
        // var up = document.getElementById("up");
        // var mp = document.getElementById("mp");
        // var t = document.getElementById("t");
        // var s = document.getElementById("s");
            return false;
        }
        // if (!t && !s || mc.value) {
        //     if (mc.value.length!=11 || mp.value.length==0) {
        //         return false;
        //     }
        // }
    } else {
        var vcode = document.getElementById("vcode");
        if (vcode.value.length != 6) {
            return false;
        }
    }
    return true;
};

// Binding events with functions.
var uc = document.getElementById("uc");
// var mc = document.getElementById("mc");
uc && (uc.onkeypress = digitOnly);
// mc && (mc.onkeypress = digitOnly);
var form = document.getElementsByTagName("form")[0];
if (form) {
    form.onsubmit = checkForm;
    form.onkeyup = function() {
        btn = document.getElementsByClassName("btn")[0];
        if (checkForm()) {
            if (btn.className.indexOf("btnValid") == -1) {
                btn.className += " btnValid";
            }
        } else {
            if (btn.className.indexOf("btnValid") != -1) {
                btn.className = btn.className.replace("btnValid", "");
            }
        }
    };
}
