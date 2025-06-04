import React from 'react';
import { Menu } from 'antd'; // Menu.Divider is part of Menu
import {
  ApiOutlined,
  SettingOutlined,
  PlayCircleOutlined,
  AppstoreOutlined,
  TranslationOutlined,
  ExperimentOutlined,
  ToolOutlined,
  DeploymentUnitOutlined,
  BookOutlined,
  EditOutlined,
  SlidersOutlined,
  GithubOutlined,
  SwitcherOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';

// 輔助函數，用於建立選單項目
export function getItem(label, key, icon, children, type) {
  return {
    key,
    icon,
    children,
    label,
    type,
  };
}

// 側邊欄主選單項目
export const siderMenuItems = [
  getItem('接口管理', 'sub1', <ApiOutlined />),
  getItem('项目设置', 'sub2', <SettingOutlined />),
  getItem('开始翻译', 'sub3', <TranslationOutlined />),
  getItem('基础设置', 'sub4', <ExperimentOutlined />),
  getItem('高级设置', 'sub5', <ToolOutlined />),
  getItem('插件设置', 'sub6', <DeploymentUnitOutlined />),
  getItem('混合翻译设置', 'sub7', <AppstoreOutlined />),
  getItem('指令词典', 'sub8', <BookOutlined />, [
    getItem('词典项1', 'opt1'),
    getItem('词典项2', 'opt2'),
  ]),
  getItem('文本替换', 'sub9', <SwitcherOutlined />, [
    getItem('替换规则1', 'opt3'),
    getItem('替换规则2', 'opt4'),
  ]),
  getItem('提示词优化', 'sub10', <SlidersOutlined />, [
    getItem('优化策略1', 'opt5'),
    getItem('优化策略2', 'opt6'),
  ]),
  getItem('StevExtraction', 'sub11', <DatabaseOutlined />, [
    getItem('提取配置1', 'opt7'),
    getItem('提取配置2', 'opt8'),
  ]),
];

// 側邊欄底部選單項目
export const bottomSiderMenuItems = [
  getItem('应用设置', 'app_settings', <SettingOutlined />),
  getItem('变换自如', 'transform', <SwitcherOutlined />),
  getItem('NEKOparapa', 'neko', <GithubOutlined />),
];


// 通用的接口操作下拉選單內容
export const interfaceActionsMenu = (interfaceName) => ({
  items: [
    {
      key: 'edit-interface',
      icon: <EditOutlined />,
      label: '編輯接口',
    },
    {
      key: 'edit-params', 
      icon: <SlidersOutlined />,
      label: '編輯參數',
    },
    {
      key: 'test-interface',
      icon: <PlayCircleOutlined />,
      label: '測試接口',
    },
    {
      type: 'divider',
    }
  ],
  onClick: (e) => console.log(`Clicked ${e.key} for ${interfaceName}`)
});