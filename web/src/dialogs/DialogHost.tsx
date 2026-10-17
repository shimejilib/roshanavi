// Renders the dialog requested through AppState (one at a time).

import { CreateInputDialog } from '../input/CreateInputDialog';
import { ImportLaunchDialog } from '../launchImport/ImportLaunchDialog';
import { LifecycleDialog } from '../lifecycle/LifecycleDialog';
import { ParamsDialog } from '../params/ParamsDialog';
import { ProjectsDialog } from '../transform/ProjectsDialog';
import { CreateTransformDialog } from '../transform/CreateTransformDialog';
import { useAppState } from '../state/AppState';
import { EdgeDialog } from './EdgeDialog';
import { ExportLaunchDialog } from './ExportLaunchDialog';
import { InterfaceDialog } from './InterfaceDialog';

export function DialogHost() {
  const { dialog } = useAppState();
  if (!dialog) return null;
  switch (dialog.kind) {
    case 'createInput':
      return <CreateInputDialog topic={dialog.topic} type={dialog.type} dummyId={dialog.dummyId} />;
    case 'createTransform':
      return <CreateTransformDialog topic={dialog.topic} type={dialog.type} transformId={dialog.transformId} />;
    case 'projects':
      return <ProjectsDialog />;
    case 'params':
      return <ParamsDialog key={dialog.nodeId} nodeId={dialog.nodeId} />;
    case 'interface':
      return <InterfaceDialog type={dialog.type} />;
    case 'edge':
      return <EdgeDialog topic={dialog.topic} node={dialog.node} dir={dialog.dir} />;
    case 'exportLaunch':
      return <ExportLaunchDialog dummyId={dialog.dummyId} />;
    case 'lifecycle':
      return <LifecycleDialog key={dialog.nodeId} nodeId={dialog.nodeId} />;
    case 'launchImport':
      return <ImportLaunchDialog />;
    default:
      return null;
  }
}
