-- GradHeat 数据库 schema
--
-- 设计约束（来自 docs/DESIGN.md 的机制 2/3/5/9，破坏任一条都会污染下游热度与博弈计算）：
--   1. 缺失一律 NULL，不填 0 —— 0 是「已知为零」，NULL 是「未知」，两者含义完全不同。
--   2. 不同学院 / 不同专业代码 / 不同培养方式 不得合并 —— 各自独立成行。
--   3. 每行都必须能追溯到 source_url + fetched_at + source_level（L1-L4）。
--   4. 事实表用 row_key（自然键的规范化哈希）做幂等去重，重复采集只更新数值不新增行。
--
-- 字符集 utf8mb4：校名含生僻字，且原始 HTML 里混有 PUA 图标字形（见 001 注释）。

SET NAMES utf8mb4;

-- ============================================================
-- 参考表
-- ============================================================

CREATE TABLE IF NOT EXISTS province (
  code    CHAR(2)     NOT NULL COMMENT '研招网 ssdm 省市代码',
  name    VARCHAR(32) NOT NULL,
  region  VARCHAR(16) NULL COMMENT '大区：华北/东北/华东/华中/华南/西南/西北',
  PRIMARY KEY (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='省市代码 → 名称';

-- ============================================================
-- 院校基础
-- ============================================================

CREATE TABLE IF NOT EXISTS school (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  dwdm            CHAR(5)      NOT NULL COMMENT '研招网招生单位代码，稳定自然键',
  sch_id          VARCHAR(16)  NULL COMMENT '研招网 schId —— 页面级标识，可能变，仅作抓取用',
  name            VARCHAR(64)  NOT NULL COMMENT '研招网招生单位名（含校区后缀，如 中国矿业大学(北京)）',
  legal_entity    VARCHAR(64)  NOT NULL COMMENT '归并后的法人院校名；分层按此字段去重',
  tier            ENUM('985','211','syl') NOT NULL COMMENT '历史分层（985/211 已于 2019 停用，仅供筛选）',
  province_code   CHAR(2)      NULL,
  area            VARCHAR(32)  NULL COMMENT '所在地，已剥离 PUA 图标字形并 trim',
  authority       VARCHAR(32)  NULL COMMENT '主管部门',
  is_syl          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '研招网返回的双一流标记',
  is_985          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '本项目按历史名单判定，非研招网字段',
  is_211          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '同上',
  is_self_line    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '自划线院校',
  has_grad_school TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '设研究生院',
  domain          VARCHAR(64)  NULL COMMENT '主域，如 pku.edu.cn',
  portal_url      VARCHAR(255) NULL COMMENT '研究生招生入口 URL（探测所得）',
  portal_score    SMALLINT     NULL COMMENT '入口匹配得分',
  portal_verified TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否通过内容校验；0 表示未验证，不代表不存在',
  source_level    ENUM('L1','L2','L3','L4') NOT NULL DEFAULT 'L1' COMMENT '见 DESIGN.md 机制 1',
  source_url      VARCHAR(512) NULL,
  fetched_at      DATETIME     NOT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_dwdm (dwdm),
  KEY idx_tier (tier),
  KEY idx_legal (legal_entity),
  KEY idx_portal_ok (portal_verified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招生单位（研招网口径）';

CREATE TABLE IF NOT EXISTS school_alias (
  alias         VARCHAR(64) NOT NULL COMMENT '校区/异地办学单位名',
  legal_entity  VARCHAR(64) NOT NULL COMMENT '所属法人院校名',
  note          VARCHAR(255) NULL COMMENT '归并依据',
  PRIMARY KEY (alias)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='口径归一表（机制 5）：研招网按招生单位分列，双一流按院校计数';

-- ============================================================
-- 招生入口探测证据（机制 2：证据留存）
-- ============================================================

CREATE TABLE IF NOT EXISTS school_portal_probe (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  school_id     INT UNSIGNED NOT NULL,
  url           VARCHAR(255) NOT NULL,
  dns_ok        TINYINT(1)   NOT NULL DEFAULT 0,
  http_status   SMALLINT     NULL COMMENT 'NULL = 未发出 HTTP（DNS 未通过或超时）',
  score         SMALLINT     NULL COMMENT '内容校验得分，NULL = 未取到页面',
  is_best       TINYINT(1)   NOT NULL DEFAULT 0,
  error         VARCHAR(255) NULL COMMENT '失败原因原文',
  fetched_at    DATETIME     NOT NULL,
  KEY idx_school (school_id),
  KEY idx_best (school_id, is_best),
  CONSTRAINT fk_probe_school FOREIGN KEY (school_id) REFERENCES school (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='入口探测逐候选记录 —— 保留失败项，未验证不等于不存在';

-- ============================================================
-- 招生专业目录（下一阶段采集目标）
-- ============================================================

CREATE TABLE IF NOT EXISTS program (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  row_key         CHAR(16)     NOT NULL COMMENT '自然键哈希，幂等去重',
  school_id       INT UNSIGNED NOT NULL,
  year            SMALLINT     NOT NULL COMMENT '招生年份',
  college_code    VARCHAR(16)  NULL COMMENT '学院/系所代码',
  college_name    VARCHAR(96)  NULL,
  major_code      VARCHAR(8)   NULL COMMENT '专业代码，如 081200 / 085400；缺失留 NULL，不臆造',
  major_name      VARCHAR(96)  NULL,
  study_mode      ENUM('全日制','非全日制') NULL COMMENT '缺失留 NULL',
  degree_type     ENUM('学硕','专硕')       NULL COMMENT '缺失留 NULL',
  is_11408        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '初试 = 政治+英一+数一+408 四门全中',
  exam_summary    VARCHAR(255) NULL COMMENT '初试科目原文，未归一 —— 归一结果不足以反推原始文本',
  source_level    ENUM('L1','L2','L3','L4') NOT NULL DEFAULT 'L2',
  source_url      VARCHAR(512) NULL,
  fetched_at      DATETIME     NOT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_rowkey (row_key),
  KEY idx_school_year (school_id, year),
  KEY idx_major (major_code),
  KEY idx_11408 (is_11408, year),
  CONSTRAINT fk_program_school FOREIGN KEY (school_id) REFERENCES school (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招生专业 × 学院 × 年份 × 培养方式，不合并';

-- 专业下的研究方向。考试科目与拟招人数在不同学校挂在不同层级：
--   有的学校按专业给数，有的按方向给数；按方向给的又可能方向间科目不同。
-- 因此方向单独成表，并允许 program 级为空（此时数据在方向行上）。
CREATE TABLE IF NOT EXISTS program_direction (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  row_key       CHAR(16)     NOT NULL,
  program_id    BIGINT UNSIGNED NOT NULL,
  direction_code VARCHAR(16) NULL COMMENT '研究方向代码',
  direction_name VARCHAR(160) NULL,
  exam_summary  VARCHAR(255) NULL COMMENT '该方向的初试科目原文',
  planned_total INT          NULL COMMENT '拟招生人数；NULL = 未公布，不等同于 0',
  planned_exempt INT         NULL COMMENT '拟接收推免人数；NULL = 未公布',
  remark        VARCHAR(512) NULL,
  source_url    VARCHAR(512) NULL,
  fetched_at    DATETIME     NOT NULL,
  UNIQUE KEY uk_rowkey (row_key),
  KEY idx_program (program_id),
  CONSTRAINT fk_dir_program FOREIGN KEY (program_id) REFERENCES program (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='研究方向 —— 不合并，因为方向间科目与计划数可能不同';

-- ============================================================
-- 分数线 / 录取统计（历史序列，供热度与博弈层使用）
-- ============================================================

CREATE TABLE IF NOT EXISTS score_line (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  row_key       CHAR(16)     NOT NULL,
  school_id     INT UNSIGNED NOT NULL,
  year          SMALLINT     NOT NULL,
  college_code  VARCHAR(16)  NULL,
  major_code    VARCHAR(8)   NULL,
  study_mode    ENUM('全日制','非全日制') NULL,
  score_type    ENUM('国家线','院校线','院系线','复试线','录取最低分','录取平均分') NOT NULL,
  total_score   SMALLINT     NULL COMMENT '总分线',
  politics      SMALLINT     NULL COMMENT '单科线：政治',
  english       SMALLINT     NULL,
  math          SMALLINT     NULL,
  subject_408   SMALLINT     NULL,
  source_level  ENUM('L1','L2','L3','L4') NOT NULL DEFAULT 'L2',
  source_url    VARCHAR(512) NULL,
  fetched_at    DATETIME     NOT NULL,
  UNIQUE KEY uk_rowkey (row_key),
  KEY idx_school_year (school_id, year),
  KEY idx_type (score_type),
  CONSTRAINT fk_score_school FOREIGN KEY (school_id) REFERENCES school (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分数线 —— 单科线 NULL 表示该校未公布该项，不代表无要求';

CREATE TABLE IF NOT EXISTS admission_stat (
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  row_key           CHAR(16)     NOT NULL,
  school_id         INT UNSIGNED NOT NULL,
  year              SMALLINT     NOT NULL,
  college_code      VARCHAR(16)  NULL,
  major_code        VARCHAR(8)   NULL,
  study_mode        ENUM('全日制','非全日制') NULL,
  applied_count     INT          NULL COMMENT '报考人数',
  admitted_count    INT          NULL COMMENT '录取人数（含推免则另注）',
  admitted_exempt   INT          NULL COMMENT '其中推免录取',
  score_min         SMALLINT     NULL,
  score_max         SMALLINT     NULL,
  score_avg         DECIMAL(6,2) NULL,
  score_median      SMALLINT     NULL,
  includes_exempt   TINYINT(1)   NULL COMMENT 'admitted_count 是否含推免；NULL = 未说明',
  remark            VARCHAR(512) NULL,
  source_level      ENUM('L1','L2','L3','L4') NOT NULL DEFAULT 'L2',
  source_url        VARCHAR(512) NULL,
  fetched_at        DATETIME     NOT NULL,
  UNIQUE KEY uk_rowkey (row_key),
  KEY idx_school_year (school_id, year),
  CONSTRAINT fk_stat_school FOREIGN KEY (school_id) REFERENCES school (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='录取统计 —— 报录比等衍生指标在此之上计算，不预先算好存储';

-- ============================================================
-- 采集批次日志（机制 9 ①③：空结果与基线跌幅必须留痕）
-- ============================================================

CREATE TABLE IF NOT EXISTS fetch_log (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  run_id        CHAR(36)     NOT NULL,
  dataset       VARCHAR(64)  NOT NULL COMMENT '如 yz_school_list / school_portal',
  target        VARCHAR(255) NULL COMMENT '本批次对象范围描述',
  started_at    DATETIME     NOT NULL,
  finished_at   DATETIME     NULL,
  rows_fetched  INT          NULL COMMENT 'NULL = 未完成/未统计',
  expected_rows INT          NULL,
  content_hash  CHAR(16)     NULL,
  baseline_note VARCHAR(255) NULL COMMENT '基线比对结论；跌幅超阈值时的告警原文',
  outcome       ENUM('ok','empty','partial','failed') NOT NULL,
  note          VARCHAR(512) NULL COMMENT '口径差异、异常说明等必须显式记录，不静默',
  UNIQUE KEY uk_run (run_id, dataset),
  KEY idx_dataset_time (dataset, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每次采集一行 —— 空结果不当作「真的没有」';