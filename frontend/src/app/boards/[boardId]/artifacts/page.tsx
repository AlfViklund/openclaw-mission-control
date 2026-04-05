import { redirect } from "next/navigation";

type BoardArtifactsPageProps = {
  params: Promise<{ boardId: string }>;
};

export default async function BoardArtifactsPage({ params }: BoardArtifactsPageProps) {
  const { boardId } = await params;
  redirect(`/artifacts?board_id=${encodeURIComponent(boardId)}`);
}
