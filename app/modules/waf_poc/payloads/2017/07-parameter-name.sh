## 탐지 구문 ##
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/index.html?>/<script>alert);/="
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/index.html?%22+onmouseover%3d%22alert(1111)%22%3E+DANUX%3C/iframe%3E%20%3Ciframe%20a%3D%22="
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/index.html?/*&prodID=*/UNION%20/*&prodID=*/SELECT%201%20&prodID=2%20&prodID=3%20FROM%20/*&prodID=*/Users%20/*&prodID=*/%20WHERE%20id=3%20?"
curl -k --resolve curl.ncurity.com:80:192.168.41.52 "http://curl.ncurity.com/index.html?/*&prodID=%2A%2F%55%4E%49%4F%4E+%2F%2A%26%70%72%6F%64%49%44%3D%2A%2F%53%45%4C%45%43%54+%31+&prodID=2%20&prodID=3%20FROM%20/*&prodID=*/Users%20/*&prodID=*/%20id=3%20?"
