## 탐지 항목 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/_vti_inf.html"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/web-INF/web.xml"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/.svn/entries"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/api/.env"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/web.config"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/META-INF/context.xm"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/.htaccess"

## 미탐 항목 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/iisstart.asp"
# .back이 확장자로 걸리기는 함. 
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/index.bak"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/index.zip"
