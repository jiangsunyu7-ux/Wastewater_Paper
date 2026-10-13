# 联系地址证据状态

用户本轮明确提供：开放数据联系地址为 **opendata@wessexwater.co.uk**，Marketplace 联系页地址为 **marketplace@wessexwater.co.uk**，并说明已由官方资料核实。因此请求材料可用前者作为建议收件人，后者仅列为备用；本轮没有发送邮件、填写表单或联系任何人。

本地旧 19 次官方查询、Stage3E 工程证据表及提供方 catalog 中未找到这两个邮箱的原文。已保存 catalog（`data/provenance/stage3b_20261011_v1/official_provider_catalog_response.bin`）包含官方开放数据页面和 Marketplace 域名的直接链接，构成本轮两个新合法获取线索。

2026-10-13（UTC 06:16:49，中国时间 14:16:49），各只读 GET 一次：

- <https://corporate.wessexwater.co.uk/our-performance/open-data-schedule>
- <https://marketplace.wessexwater.co.uk/>

两次均在连接隧道阶段返回 `Tunnel connection failed: 403 Forbidden`，没有收到官方网页正文。这不是官网本身的 HTTP 回应，也不能视为官网拒绝请求或邮箱失效。未重试失败 URL，未使用第三次请求猜测联系页。

故当前证据级别保留为 **USER_REPORTED_OFFICIALLY_VERIFIED**，本环境未独立取得官方邮箱引文。CSV 分别登记地址来源、官网 URL 线索、旧 catalog SHA、查询时间、失败与未发送状态；`CONTACT_ACCESS_LEDGER.json` 登记请求和失败文件 SHA。两个 0 字节 `.bin` 仅表示没有响应正文，不能作为官方页面备份引用。

如需对外引用邮箱官方依据，请提供已经核验的联系页准确 URL 和网页/PDF截图原件。该补件只影响联系地址出处，不解决设施独立性、日界线或实时可得性门槛。
