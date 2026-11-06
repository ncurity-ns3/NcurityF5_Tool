## 탐지 항목 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=<SCRIPT>alert("XSS");</SCRIPT>"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=PFNDUklQVD5hbGVydCgiWFNTIik7PC9TQ1JJUFQ+"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=><SCRIPT>alert("XSS");</SCRIPT>"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=”>"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=\";alert('XSS');//"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=<ScRiPt>aLeRt("XSS");</sCrIpT>"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=<SCRIPT>alert("XSS");</SCRIPT>"