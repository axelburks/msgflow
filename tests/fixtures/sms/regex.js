const fs = require('fs');

fs.readFile(`${__dirname}/sms.json`, 'utf8', (err, data) => {
  if (err) {
    console.error('Error reading file:', err);
    return;
  }
  try {
    const jsonObject = JSON.parse(data);
    for (let i = 0; i < jsonObject.length; i++) {
      // 【标记正则】可直接应用于 base.py::pattern_flags 或 smsforwarder
      // (?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode)

      // 【验证码正则】可直接应用于 base.py::pattern_captchas
      // (?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)

      // 验证码位置：两种情况，验证码在【标记正则】后，验证码在【标记正则】前；且距离不能超过60个字符
      // (?<=(【标记正则】)[\s\S]{0,60})【验证码正则】
      // 【验证码正则】(?=[\s\S]{0,60}(【标记正则】))

      // 两种位置均需匹配：通过｜组合到一起
      // (?<=(【标记正则】)[\s\S]{0,60})【验证码正则】|【验证码正则】(?=[\s\S]{0,60}(【标记正则】))

      // 完整短信：添加首尾字符以匹配完整短信
      // ([\s\S]*?)((?<=(【标记正则】)[\s\S]{0,60})【验证码正则】|【验证码正则】(?=[\s\S]{0,60}(【标记正则】)))([\s\S]*)

      // 完整短信：【验证码正则】替换为对应内容
      // ([\s\S]*?)((?<=(【标记正则】)[\s\S]{0,60})(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)|(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)(?=[\s\S]{0,60}(【标记正则】)))([\s\S]*)

      // 完整短信：【标记正则】替换为对应内容，若最后加上 `===$2` 则可应用于 smsforwarder
      // ([\s\S]*?)((?<=((?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode))[\s\S]{0,60})(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)|(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)(?=[\s\S]{0,60}((?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode))))([\s\S]*)

      const regex = /([\s\S]*?)((?<=((?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode))[\s\S]{0,60})(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)|(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)(?=[\s\S]{0,60}((?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode))))([\s\S]*)/gm;
      
      const text = jsonObject[i]["text"]
      const code_expected = jsonObject[i]?.code_expected ?? null
      let fiter_code = regex.exec(text)
      if (code_expected) {
        if (fiter_code) {
          if (code_expected != fiter_code[2]) {
            console.log("text: ", text)
            console.log("expected: ", code_expected, "got: ", fiter_code[2])
            console.log("")
          }
        } else {
          console.log("text: ", text)
          console.log("expected: ", code_expected, "got: ", JSON.stringify(fiter_code))
          console.log("")
        }
      } else {
        if (fiter_code) {
          console.log("text: ", text)
          console.log("expected: ", code_expected, "got: ", fiter_code[2])
          console.log("")
        }
      }
    }
  } catch (parseErr) {
    console.error('Error parsing JSON:', parseErr);
  }
});