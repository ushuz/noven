var digitOnly = function(event) {return (/[\d]/.test(String.fromCharCode(event.keyCode)))};
var checkForm = function() {
    if (String($("form")[0].action).indexOf("verify") == -1) {
        if ($("#uc").val().length!=9 || $("#mc").val().length!=11 || $("#up").val().length==0 || $("#mp").val().length==0) {
            return false;
        }
    } else {
        if ($("#vcode").val().length != 6) {
            return false;
        }
    }
    return true;
};

$(document).ready(function(){
    $("#mc").bind("keypress", digitOnly);
    $("#uc").bind("keypress", digitOnly);
    $("form").bind("submit", checkForm);
    $("form").bind("keyup", function() {if (checkForm()) {$(".btn").addClass("btnValid");} else {$(".btn").removeClass("btnValid");}});
});