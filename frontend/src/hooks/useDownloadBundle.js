import { useCallback } from 'react';
import JSZip from 'jszip';
import { message } from 'antd';
import { downloadBlob, renameExtension } from '../utils/download';

/**
 * 提供「下載單檔結果」與「打包所有已完成檔案」兩個 helper。
 */
export function useDownloadBundle(fileList) {
  const downloadFile = useCallback((content, fileName, format) => {
    downloadBlob(content, renameExtension(fileName, format));
  }, []);

  const downloadAllFiles = useCallback(async (format) => {
    const completedFiles = fileList.filter(f => f.status === 'completed' && f.result);

    if (completedFiles.length === 0) {
      message.warning('沒有已完成的檔案可以下載！');
      return;
    }

    try {
      message.loading({ content: '正在打包檔案...', key: 'zipDownload' });

      const zip = new JSZip();
      completedFiles.forEach((file) => {
        const content = file.result[format] || '';
        if (content) {
          zip.file(renameExtension(file.name, format), content);
        }
      });

      const zipBlob = await zip.generateAsync({ type: 'blob' });
      const formatUpper = format.toUpperCase();
      const dateStr = new Date().toISOString().slice(0, 10);
      downloadBlob(zipBlob, `transcripts_${formatUpper}_${dateStr}.zip`);

      message.success({
        content: `已成功下載 ${completedFiles.length} 個 ${formatUpper} 檔案的壓縮包！`,
        key: 'zipDownload',
      });
    } catch (error) {
      console.error('打包下載失敗:', error);
      message.error({
        content: '打包下載失敗，請稍後再試',
        key: 'zipDownload',
      });
    }
  }, [fileList]);

  return { downloadFile, downloadAllFiles };
}
