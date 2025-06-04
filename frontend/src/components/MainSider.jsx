import React from 'react';
import { Layout, Menu, Typography } from 'antd';
import { siderMenuItems, bottomSiderMenuItems } from '../constants/menuConfig';
import { customDarkTheme } from '../theme/themeConfig';

const { Sider } = Layout;
const { Title } = Typography;

const MainSider = ({ collapsed, onCollapse }) => {
  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      width={250}
      style={{
        background: customDarkTheme.components.Layout.siderBg,
        paddingTop: '0px',
      }}
      trigger={null} // 隱藏預設的收合觸發器
    >
      <Menu
        theme="dark"
        defaultSelectedKeys={['sub1']} // 預設選中的項目
        mode="inline"
        items={siderMenuItems}
        style={{ background: customDarkTheme.components.Layout.siderBg }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '0px',
          width: '100%',
          paddingLeft: '0px', // 調整對齊
          paddingRight: '0px',
          background: customDarkTheme.components.Layout.siderBg,
        }}
      >
        <Menu
          theme="dark"
          mode="inline"
          selectable={false} // 底部選單項目不可選中
          items={bottomSiderMenuItems}
          style={{ background: customDarkTheme.components.Layout.siderBg }}
        />
      </div>
    </Sider>
  );
};

export default MainSider;